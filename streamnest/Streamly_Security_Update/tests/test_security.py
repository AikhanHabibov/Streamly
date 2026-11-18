import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD,SEED,installer,csrf,password_stage,admin_login,owner,add_video,submit

@pytest.mark.parametrize("stamp,expected",[
    (59,"94287082"),(1111111109,"07081804"),(1111111111,"14050471"),
    (1234567890,"89005924"),(2000000000,"69279037"),(20000000000,"65353130")])
def test_rfc6238_sha1_vectors(platform,stamp,expected):
    c,core,admin,sec,setup,codes=platform
    assert sec.totp(SEED,stamp,digits=8)==expected

def test_password_alone_and_legacy_admin_cookie_cannot_grant_rights(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    assert response.status_code==303 and response.headers["location"]=="/admin/mfa"
    assert not [x for x in c.cookies.jar if x.name==admin.COOKIE]
    assert c.get("/admin").status_code==401
    assert c.post("/admin/videos/anything/delete").status_code==401
    raw="old-password-only-session"
    with core.connect() as db:
        db.execute("INSERT INTO streamly_admin_sessions VALUES(?,?,?)",(sec.sha(raw),"admin",core.now()+1000))
    c.cookies.set(admin.COOKIE,raw)
    assert c.get("/admin/users").status_code==401

def test_successful_totp_creates_bound_mfa_session(platform):
    c,core,admin,sec,setup,codes=platform
    admin_login(c,core,sec)
    assert c.get("/admin").status_code==200
    with core.connect() as db:
        session=db.execute("SELECT * FROM streamly_mfa_sessions").fetchone()
        assert session["method"]=="totp"
        assert db.execute("SELECT COUNT(*) FROM streamly_mfa_challenges").fetchone()[0]==0
    assert c.get("/admin/security").status_code==200

def test_enrollment_is_encrypted_and_key_file_is_private(platform):
    c,core,admin,sec,setup,codes=platform
    with core.connect() as db:
        row=db.execute("SELECT secret_cipher FROM streamly_mfa").fetchone()
        assert SEED not in row["secret_cipher"]
        assert sec.cipher().decrypt(row["secret_cipher"].encode()).decode()==SEED
    assert os.stat(sec.key_path()).st_mode & 0o077==0
    assert os.stat(sec.key_path().parent).st_mode & 0o077==0

def test_wrong_password_never_creates_mfa_challenge(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c,password="incorrect")
    assert response.status_code==400
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM streamly_mfa_challenges").fetchone()[0]==0

def test_missing_enrollment_fails_closed(platform):
    c,core,admin,sec,setup,codes=platform
    with core.connect() as db:db.execute("DELETE FROM streamly_mfa")
    token,response=password_stage(c)
    assert response.status_code==503
    assert c.get("/admin").status_code==401

def test_same_totp_cannot_be_reused_in_new_login(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    code=sec.totp(SEED,core.now())
    assert c.post("/admin/mfa",data={"csrf":token,"code":code},follow_redirects=False).headers["location"]=="/admin"
    token,response=password_stage(c)
    assert c.post("/admin/mfa",data={"csrf":token,"code":code},follow_redirects=False).status_code==400
    assert c.get("/admin").status_code==401

def test_challenge_expires_and_password_reset_invalidates_proof(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    with core.connect() as db:db.execute("UPDATE streamly_mfa_challenges SET expires_at=?",(core.now()-1,))
    result=c.post("/admin/mfa",data={"csrf":token,"code":sec.totp(SEED,core.now())},follow_redirects=False)
    assert result.headers["location"]=="/admin/login"
    token,response=password_stage(c)
    with core.connect() as db:db.execute("UPDATE streamly_admin_accounts SET password_hash=?",(core.ph.hash("new-password-for-admin"),))
    result=c.post("/admin/mfa",data={"csrf":token,"code":sec.totp(SEED,core.now())},follow_redirects=False)
    assert result.headers["location"]=="/admin/login"
    assert c.get("/admin").status_code==401

def test_five_bad_codes_exhaust_one_challenge(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    excluded={sec.totp(SEED,core.now()+offset) for offset in (-30,0,30)}
    wrong=next(f"{n:06d}" for n in range(10) if f"{n:06d}" not in excluded)
    for _ in range(5):
        assert c.post("/admin/mfa",data={"csrf":token,"code":wrong},follow_redirects=False).status_code==400
    result=c.post("/admin/mfa",data={"csrf":token,"code":sec.totp(SEED,core.now())},follow_redirects=False)
    assert result.headers["location"]=="/admin/login"
    with core.connect() as db:
        assert db.execute("SELECT attempts FROM streamly_mfa_challenges").fetchone()[0]==5

def test_recovery_is_one_time_and_hashed(platform):
    c,core,admin,sec,setup,codes=platform
    admin_login(c,core,sec,recovery=codes[0].lower().replace("-"," "))
    assert c.get("/admin").status_code==200
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM streamly_mfa_recovery WHERE used_at IS NOT NULL").fetchone()[0]==1
        stored=[r[0] for r in db.execute("SELECT code_hash FROM streamly_mfa_recovery")]
        assert codes[0] not in stored
    token,response=password_stage(c)
    assert c.post("/admin/mfa",data={"csrf":token,"code":codes[0]},follow_redirects=False).status_code==400

def test_recovery_concurrent_use_only_succeeds_once(platform):
    c,core,admin,sec,setup,codes=platform
    clients=[TestClient(core.app),TestClient(core.app)]
    tokens=[password_stage(client)[0] for client in clients]
    def attempt(index):
        return clients[index].post("/admin/mfa",data={"csrf":tokens[index],"code":codes[1]},follow_redirects=False).status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        assert sorted(results)==[303,400]
        with core.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM streamly_mfa_sessions").fetchone()[0]==1
    finally:
        for client in clients:client.close()

def test_mfa_csrf_origin_and_forgery_are_rejected(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    code=sec.totp(SEED,core.now())
    assert c.post("/admin/mfa",data={"code":code}).status_code==403
    assert c.post("/admin/mfa",data={"csrf":token,"code":code},headers={"origin":"https://evil.example"}).status_code==403
    c.cookies.set(sec.CHALLENGE_COOKIE,"forged",path="/admin")
    assert c.get("/admin/mfa",follow_redirects=False).headers["location"]=="/admin/login"

def test_reset_invalidates_all_sessions_and_old_codes(platform):
    c,core,admin,sec,setup,codes=platform
    admin_login(c,core,sec)
    new_codes=setup.make_codes()
    new_seed=base64.b32encode(b"abcdefghijklmnopqrst").decode()
    with core.connect() as db:
        setup.save_enrollment(db,new_seed,core.now()//30,new_codes,setup.ensure_key())
    assert c.get("/admin").status_code==401
    with core.connect() as db:
        assert not db.execute("SELECT 1 FROM streamly_mfa_recovery WHERE code_hash=?",(sec.recovery_hash("admin",codes[0]),)).fetchone()

def test_clock_window_and_enrollment_counter_replay(platform):
    c,core,admin,sec,setup,codes=platform
    stamp=core.now()
    assert sec.match_counter(SEED,sec.totp(SEED,stamp-30),stamp) is not None
    assert sec.match_counter(SEED,sec.totp(SEED,stamp-90),stamp) is None
    counter=stamp//30
    assert sec.match_counter(SEED,sec.totp(SEED,stamp),stamp,last_counter=counter) is None

def test_missing_key_cannot_create_totp_session_but_recovery_still_works(platform):
    c,core,admin,sec,setup,codes=platform
    token,response=password_stage(c)
    sec.key_path().unlink()
    assert c.post("/admin/mfa",data={"csrf":token,"code":sec.totp(SEED,core.now())},follow_redirects=False).status_code==503
    assert c.get("/admin").status_code==401
    assert c.post("/admin/mfa",data={"csrf":token,"code":codes[2]},follow_redirects=False).headers["location"]=="/admin"

def test_secure_cookie_attributes_and_no_secret_in_browser(platform,monkeypatch):
    c,core,admin,sec,setup,codes=platform
    monkeypatch.setattr(core,"PRODUCTION",True)
    token,response=password_stage(c)
    cookies=response.headers.get_list("set-cookie")
    challenge=next(v for v in cookies if v.startswith(sec.CHALLENGE_COOKIE+"="))
    assert "Secure" in challenge and "HttpOnly" in challenge and "SameSite=strict" in challenge
    assert "Path=/admin" in challenge
    # Secure cookies are not sent over the test HTTP transport; inspect rendering on a fresh development client.
    monkeypatch.setattr(core,"PRODUCTION",False)
    token,response=password_stage(c)
    page=c.get("/admin/mfa").text
    assert SEED not in page and all(code not in page for code in codes)

def test_report_video_creation_dedup_and_user_visibility(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core)
    token=owner(c,core)
    assert submit(c,"video",vid,token).status_code==303
    assert "duplicate=1" in submit(c,"video",vid,token).headers["location"]
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM streamly_reports").fetchone()[0]==1
        db.execute("UPDATE streamly_reports SET admin_note='ADMIN ONLY SECRET NOTE'")
    page=c.get("/reports/mine").text
    assert "A video" in page and "ADMIN ONLY SECRET NOTE" not in page
    owner(c,core,2)
    assert "A video" not in c.get("/reports/mine").text

def test_reports_require_active_user_and_cannot_reveal_private_videos(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core,state="pending")
    assert c.get(f"/report/video/{vid}").status_code==401
    owner(c,core,1)
    assert c.get(f"/report/video/{vid}").status_code==404
    with core.connect() as db:
        db.execute("INSERT INTO streamly_user_safety(user_id,blocked,updated_at) VALUES(1,1,?)",(core.now(),))
    assert c.get("/reports/mine").status_code==403

def test_report_rejects_csrf_changed_content_and_invalid_category(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core)
    token=owner(c,core)
    page=c.get(f"/report/video/{vid}")
    version=re.search(r'name="version" value="([^"]+)"',page.text).group(1)
    payload={"csrf":token,"version":version,"category":"Spam / Betrug","reason":"Detailed enough to submit"}
    assert c.post(f"/report/video/{vid}",data={**payload,"csrf":"bad"}).status_code==403
    assert c.post(f"/report/video/{vid}",data={**payload,"category":"INVALID"}).status_code==400
    with core.connect() as db:db.execute("UPDATE videos SET title='changed' WHERE id=?",(vid,))
    assert c.post(f"/report/video/{vid}",data=payload).status_code==409
    with core.connect() as db:assert db.execute("SELECT COUNT(*) FROM streamly_reports").fetchone()[0]==0

def test_admin_can_review_and_remove_reported_video_with_cascades(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core)
    token=owner(c,core)
    submit(c,"video",vid,token)
    with core.connect() as db:
        db.execute("INSERT INTO likes VALUES(1,?)",(vid,))
        db.execute("INSERT INTO comments(user_id,video_id,body,created_at) VALUES(1,?,'a comment',?)",(vid,core.now()))
    token=admin_login(c,core,sec)
    assert c.get("/admin/reports").status_code==200
    assert c.get("/admin/reports/1").status_code==200
    response=c.post("/admin/reports/1/action",data={"csrf":token,"action":"remove_video","note":"Reviewed"},follow_redirects=False)
    assert response.status_code==303
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM likes").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]==0
        assert db.execute("SELECT status FROM streamly_reports").fetchone()[0]=="resolved"
    assert not (core.MEDIA/(vid+".mp4")).exists() and not (core.MEDIA/(vid+".jpg")).exists()

def test_reports_never_automatically_hide_or_delete_video(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core)
    submit(c,"video",vid,token)
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==1
        assert db.execute("SELECT state FROM streamly_video_moderation").fetchone()[0]=="approved"

def test_reporter_cannot_access_admin_queue_or_take_action(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    assert c.get("/admin/reports").status_code==401
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"remove_video"}).status_code==401
    assert c.get("/admin/security").status_code==401

def test_comment_moderation_targets_comment_author_not_video_creator(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core,uid=1)
    with core.connect() as db:
        db.execute("INSERT INTO comments(id,user_id,video_id,body,created_at) VALUES(7,2,?,'Bad comment',?)",(vid,core.now()))
    token=owner(c,core,1);submit(c,"comment","7",token)
    token=admin_login(c,core,sec)
    c.post("/admin/reports/1/action",data={"csrf":token,"action":"block_account","note":"Abuse"})
    with core.connect() as db:
        assert db.execute("SELECT blocked FROM streamly_user_safety WHERE user_id=2").fetchone()[0]==1
        assert not db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=1 AND blocked=1").fetchone()

def test_reused_comment_id_is_not_deleted_by_old_report(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core,uid=1)
    with core.connect() as db:
        db.execute("INSERT INTO comments VALUES(7,2,?,'Original',?)",(vid,core.now()))
    token=owner(c,core);submit(c,"comment","7",token)
    with core.connect() as db:
        db.execute("DELETE FROM comments WHERE id=7")
        db.execute("INSERT INTO comments VALUES(7,2,?,'Original',?)",(vid,core.now()))
    assert submit(c,"comment","7",token).headers["location"].endswith("sent=1")
    token=admin_login(c,core,sec)
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"remove_comment"}).status_code==409
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM comments WHERE id=7").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM streamly_reports").fetchone()[0]==2
    assert c.post("/admin/reports/2/action",data={"csrf":token,"action":"remove_comment"},follow_redirects=False).status_code==303

def test_deleted_account_id_reuse_cannot_ban_new_person(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    with core.connect() as db:
        db.execute("DELETE FROM users WHERE id=2")
        db.execute("INSERT INTO users VALUES(2,'bob','New Bob',?)",(core.now(),))
    token=admin_login(c,core,sec)
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"block_account"}).status_code==409
    with core.connect() as db:assert not db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=2 AND blocked=1").fetchone()

def test_live_report_can_disable_stream_and_permissions(platform):
    c,core,admin,sec,setup,codes=platform
    with core.connect() as db:
        db.execute("INSERT INTO streamly_live_channels VALUES(2,'live_bob','hash','Bob Live','About',1)")
        db.execute("INSERT INTO streamly_user_safety(user_id,can_stream,updated_at) VALUES(2,1,?)",(core.now(),))
    token=owner(c,core);submit(c,"live","bob",token)
    token=admin_login(c,core,sec)
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"stop_live"},follow_redirects=False).status_code==303
    with core.connect() as db:
        row=db.execute("SELECT enabled,key_hash FROM streamly_live_channels").fetchone()
        assert row["enabled"]==0 and not row["key_hash"]
        assert db.execute("SELECT can_stream FROM streamly_user_safety WHERE user_id=2").fetchone()[0]==0

def test_report_limits_statuses_and_admin_csrf(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    token=admin_login(c,core,sec)
    assert c.post("/admin/reports/1/action",data={"csrf":"wrong","action":"remove_video"}).status_code==403
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"remove_comment"}).status_code==400
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"unknown"}).status_code==400
    assert c.post("/admin/reports/1/action",data={"csrf":token,"action":"dismissed","note":"No issue"},follow_redirects=False).status_code==303
    with core.connect() as db:assert db.execute("SELECT status FROM streamly_reports").fetchone()[0]=="dismissed"

def test_reopening_old_report_with_new_open_case_is_conflict_not_server_error(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    admin_token=admin_login(c,core,sec)
    c.post("/admin/reports/1/action",data={"csrf":admin_token,"action":"dismissed"})
    submit(c,"video",vid,token)
    assert c.post("/admin/reports/1/action",data={"csrf":admin_token,"action":"reviewing"}).status_code==409

def test_untrusted_html_is_escaped_and_secrets_are_not_audited(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core)
    with core.connect() as db:db.execute("UPDATE videos SET title='<script>bad()</script>' WHERE id=?",(vid,))
    token=owner(c,core);submit(c,"video",vid,token,reason="<script>bad()</script> report text")
    admin_login(c,core,sec,recovery=codes[4])
    page=c.get("/admin/reports/1").text
    assert "&lt;script&gt;" in page and "<script>bad()" not in page
    with core.connect() as db:
        audit=json.dumps([dict(r) for r in db.execute("SELECT * FROM streamly_admin_audit")])
    assert PASSWORD not in audit and SEED not in audit and codes[4] not in audit

def test_installer_backup_patches_login_and_is_idempotent(original_project):
    install=installer();old_admin=(original_project/"app/streamly_admin.py").read_bytes()
    backup=install.install(original_project)
    assert (backup/"files/app/streamly_admin.py").read_bytes()==old_admin
    source=(original_project/"app/streamly_admin.py").read_text()
    assert "return security_begin_admin_mfa(request, db, account)" in source
    # Password-only cookie creation was removed from this function.
    tree=__import__("ast").parse(source)
    fn=next(n for n in tree.body if isinstance(n,__import__("ast").AsyncFunctionDef) and n.name=="login")
    block="\n".join(source.splitlines()[fn.lineno-1:fn.end_lineno])
    assert "response.set_cookie" not in block and 'raw = secrets.token_urlsafe(32)' not in block
    install.install(original_project)
    assert (original_project/"app/streamly_admin.py").read_text()==source
    assert (original_project/"app/main.py").read_text().count("app.include_router(streamly_security_router)")==1
    assert (original_project/".env").read_text()=="DOMAIN=unchanged.example\n"
    deps=(original_project/"requirements.lock").read_text()
    assert "cffi==1.17.1" not in deps and "cffi>=2.0.0,<3" in deps and "cryptography>=" in deps
    assert "source / \"secrets\"" in (original_project/"scripts/backup.py").read_text()

def test_unknown_templates_abort_before_changing_source(original_project):
    path=original_project/"app/templates/watch.html";path.write_text("Custom unrecognized template")
    before=(original_project/"app/streamly_admin.py").read_bytes()
    with pytest.raises(ValueError):installer().install(original_project)
    assert before==(original_project/"app/streamly_admin.py").read_bytes()
    assert not (original_project/"streamly-security-backups").exists()


def test_recovery_codes_are_independent_random_128_bit_values(platform):
    c,core,admin,sec,setup,codes=platform
    assert len(codes)==len(set(codes))==10
    assert all(re.fullmatch(r"[A-F0-9]{8}(?:-[A-F0-9]{8}){3}",code) for code in codes)

def test_two_challenges_cannot_reuse_one_totp_concurrently(platform):
    c,core,admin,sec,setup,codes=platform
    clients=[TestClient(core.app),TestClient(core.app)]
    tokens=[password_stage(client)[0] for client in clients]
    otp=sec.totp(SEED,core.now())
    try:
        def attempt(index):
            return clients[index].post("/admin/mfa",data={"csrf":tokens[index],"code":otp},follow_redirects=False).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        assert sorted(results)==[303,400]
    finally:
        for client in clients:client.close()

def test_reporter_deletion_does_not_assign_old_reports_to_new_account(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    with core.connect() as db:
        db.execute("DELETE FROM users WHERE id=1")
        db.execute("INSERT INTO users VALUES(1,'alice','Other Alice',?)",(core.now(),))
        assert db.execute("SELECT reporter_id FROM streamly_reports").fetchone()[0] is None
    owner(c,core,1)
    assert "A video" not in c.get("/reports/mine").text

def test_report_submission_account_rate_limit(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core)
    for index in range(11):result=submit(c,"video",vid,token)
    assert result.status_code==429

def test_report_action_checks_origin_even_with_valid_mfa(platform):
    c,core,admin,sec,setup,codes=platform
    vid=add_video(core);token=owner(c,core);submit(c,"video",vid,token)
    token=admin_login(c,core,sec)
    response=c.post("/admin/reports/1/action",data={"csrf":token,"action":"remove_video"},headers={"origin":"https://evil.example"})
    assert response.status_code==403
    with core.connect() as db:assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==1

def test_cli_enrollment_confirms_app_code_and_never_prints_password(platform,monkeypatch,capsys):
    import sys
    c,core,admin,sec,setup,codes=platform
    captured=[]
    calls=[]
    def answer(prompt):
        calls.append(prompt)
        if len(calls)==1:return PASSWORD
        output=capsys.readouterr().out;captured.append(output)
        seed=re.search(r"GEHEIMER EINRICHTUNGSSCHLÜSSEL: ([A-Z2-7]+)",output).group(1)
        return sec.totp(seed,core.now())
    monkeypatch.setattr(setup.getpass,"getpass",answer)
    monkeypatch.setattr(sys,"argv",["setup","--reset"])
    setup.main()
    output="".join(captured)+capsys.readouterr().out
    assert PASSWORD not in output
    assert "Wiederherstellungscodes" in output and "NÄCHSTEN App-Code" in output
    with core.connect() as db:
        assert db.execute("SELECT last_counter FROM streamly_mfa").fetchone()[0]==core.now()//30
        assert db.execute("SELECT COUNT(*) FROM streamly_mfa_recovery WHERE used_at IS NULL").fetchone()[0]==10

def test_unknown_admin_source_aborts_without_changes(original_project):
    admin_path=original_project/"app/streamly_admin.py"
    source=admin_path.read_text().replace("raw = secrets.token_urlsafe(32)","raw = 'unexpected-custom-authentication'")
    admin_path.write_text(source)
    with pytest.raises(ValueError):installer().install(original_project)
    assert admin_path.read_text()==source and not (original_project/"streamly-security-backups").exists()
