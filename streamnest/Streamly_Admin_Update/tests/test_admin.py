import json
import re
import sqlite3

import pytest

from conftest import installer,csrf,admin_login,owner,add_video

def test_no_default_weak_password_and_argon2(platform):
    c,core,admin,setup,live=platform
    with pytest.raises(ValueError):setup.validate_password("12345678")
    with pytest.raises(ValueError):setup.validate_password("123456789012345")
    with core.connect() as db:
        row=db.execute("SELECT * FROM streamly_admin_accounts").fetchone()
        assert row["password_hash"].startswith("$argon2id$")
        assert "a-real-test-admin-password" not in row["password_hash"]
    token=csrf(c)
    assert c.post("/admin/login",data={"csrf":token,"password":"12345678"}).status_code==400

def test_admin_session_separate_cookie_hashed_and_logout(platform):
    c,core,admin,setup,live=platform
    token=admin_login(c)
    assert c.get("/admin").status_code==200
    cookie=next(x for x in c.cookies.jar if x.name==admin.COOKIE)
    assert cookie._rest.get("HttpOnly") is None and "HttpOnly" in cookie._rest
    assert cookie._rest["SameSite"]=="strict"
    with core.connect() as db:
        raw=db.execute("SELECT token_hash FROM streamly_admin_sessions").fetchone()[0]
        assert raw==admin.hashed(cookie.value) and raw!=cookie.value
    assert c.post("/admin/logout",data={"csrf":token},follow_redirects=False).status_code==303
    assert c.get("/admin",follow_redirects=False).status_code==303

def test_regular_user_cannot_use_admin_routes(platform):
    c,core,admin,setup,live=platform
    token=owner(c,core)
    vid=add_video(core)
    for path in ["/admin/users","/admin/audit",f"/admin/videos/{vid}"]:
        assert c.get(path).status_code==401
    assert c.post(f"/admin/videos/{vid}/delete",data={"csrf":token}).status_code==401
    assert c.post("/admin/users/2/update",data={"csrf":token,"action":"rename","display_name":"Hacked"}).status_code==401
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==1

def test_new_uploads_are_pending_and_hidden_from_guest_direct_links(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,title="Secret title")
    with core.connect() as db:
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]=="pending"
    assert not c.get("/").json()["videos"]
    assert not c.get("/channel/alice").json()["videos"]
    for path in [f"/watch/{vid}",f"/media/{vid}",f"/poster/{vid}"]:
        assert c.get(path).status_code==404
    token=csrf(c)
    assert c.post(f"/api/videos/{vid}/view",headers={"x-csrf-token":token}).status_code==404

def test_owner_and_admin_can_preview_but_other_user_cannot(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    owner(c,core,1)
    assert c.get(f"/watch/{vid}").status_code==200
    assert c.get(f"/media/{vid}",headers={"Range":"bytes=0-9"}).status_code==206
    assert c.get(f"/poster/{vid}").status_code==200
    assert c.get(f"/media/{vid}").headers["cache-control"]=="no-store"
    owner(c,core,2)
    assert c.get(f"/watch/{vid}").status_code==404
    admin_login(c)
    assert c.get(f"/watch/{vid}").status_code==200
    assert c.get(f"/admin/videos/{vid}").status_code==200

def test_admin_approve_reject_and_public_visibility(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/moderate",data={"csrf":token,"state":"approved"},follow_redirects=False).status_code==303
    c.post("/admin/logout",data={"csrf":token},follow_redirects=False)
    assert c.get(f"/watch/{vid}").status_code==200
    assert len(c.get("/").json()["videos"])==1
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/moderate",data={"csrf":token,"state":"rejected","reason":"Unpassender Inhalt"},follow_redirects=False).status_code==303
    c.post("/admin/logout",data={"csrf":token},follow_redirects=False)
    assert c.get(f"/watch/{vid}").status_code==404
    assert not c.get("/").json()["videos"]

def test_approval_does_not_override_blocked_creator(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    token=admin_login(c)
    c.post("/admin/users/1/update",data={"csrf":token,"action":"block","reason":"Abuse"})
    c.post(f"/admin/videos/{vid}/moderate",data={"csrf":token,"state":"approved"})
    c.post("/admin/logout",data={"csrf":token},follow_redirects=False)
    assert c.get(f"/watch/{vid}").status_code==404

def test_creator_cannot_bypass_review_by_editing_approved_metadata(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,state="approved")
    token=owner(c,core)
    c.post(f"/studio/{vid}/edit",data={"csrf":token,"title":"Changed after approval"})
    with core.connect() as db:
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]=="pending"
    assert not c.get("/").json()["videos"]
    assert c.get(f"/watch/{vid}").status_code==200

def test_admin_renames_video_and_channel_name(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,state="approved")
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/edit",data={"csrf":token,"title":"New title","description":"New text","category":"Wissen"},follow_redirects=False).status_code==303
    assert c.post("/admin/users/1/update",data={"csrf":token,"action":"rename","display_name":"New Alice"},follow_redirects=False).status_code==303
    with core.connect() as db:
        v=db.execute("SELECT title FROM videos WHERE id=?",(vid,)).fetchone()[0]
        u=db.execute("SELECT display_name,username FROM users WHERE id=1").fetchone()
        state=db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]
    assert v=="New title" and u["display_name"]=="New Alice" and u["username"]=="alice"
    assert state=="pending"

def test_admin_delete_cascades_media_and_audits(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    with core.connect() as db:
        db.execute("INSERT INTO likes VALUES(1,?)",(vid,))
        db.execute("INSERT INTO comments(user_id,video_id,body,created_at) VALUES(1,?,'Test',?)",(vid,core.now()))
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/delete",data={"csrf":token},follow_redirects=False).status_code==303
    with core.connect() as db:
        for table in ["videos","likes","comments","streamly_video_moderation"]:
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM streamly_admin_audit WHERE action='video_delete'").fetchone()[0]==1
    assert not (core.MEDIA/(vid+".mp4")).exists()
    assert not (core.MEDIA/(vid+".jpg")).exists()

def test_missing_csrf_and_wrong_origin_cannot_change_admin_data(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/delete",data={}).status_code==403
    assert c.post(f"/admin/videos/{vid}/delete",data={"csrf":token},headers={"origin":"https://evil.example"}).status_code==403
    assert c.post("/admin/users/1/update",data={"csrf":"bad","action":"block","reason":"Test"}).status_code==403
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==1

def test_block_revokes_sessions_stream_key_and_public_search(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,state="approved")
    normal_token=owner(c,core)
    with core.connect() as db:
        db.execute("INSERT INTO streamly_live_channels(user_id,path,key_hash,title) VALUES(1,?,'old-hash','A live')",("live_"+"a"*32,))
    token=admin_login(c)
    c.post("/admin/users/1/update",data={"csrf":token,"action":"block","reason":"Wiederholter Missbrauch"})
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=1").fetchone()[0]==0
        channel=db.execute("SELECT enabled,key_hash FROM streamly_live_channels WHERE user_id=1").fetchone()
        assert channel["enabled"]==0 and not channel["key_hash"]
    c.post("/admin/logout",data={"csrf":csrf(c)},follow_redirects=False)
    assert c.get(f"/watch/{vid}").status_code==404
    assert not c.get("/?q=alice").json()["creators"]
    assert c.get("/channel/alice").status_code==404

def test_blocked_user_login_and_stale_logged_in_actions_are_denied(platform):
    c,core,admin,setup,live=platform
    token=owner(c,core)
    with core.connect() as db:
        db.execute("INSERT INTO streamly_user_safety(user_id,blocked,updated_at) VALUES(1,1,?)",(core.now(),))
    assert c.get("/studio").status_code==403
    assert c.post("/login",data={"csrf":token,"username":"alice","password":"normal-user-password-2026"}).status_code==403

def test_live_is_denied_by_default_and_granted_separately(platform):
    c,core,admin,setup,live=platform
    token=owner(c,core)
    assert c.post("/studio/live/key",data={"csrf":token}).status_code==403
    token=admin_login(c)
    assert c.post("/admin/users/1/update",data={"csrf":token,"action":"allow_live"},follow_redirects=False).status_code==303
    # Normal owner cookie remains separate from the admin cookie.
    assert c.post("/studio/live/key",data={"csrf":token}).status_code==200
    c.post("/admin/users/1/update",data={"csrf":token,"action":"deny_live"})
    assert c.post("/studio/live/key",data={"csrf":token}).status_code==403
    with core.connect() as db:
        assert not db.execute("SELECT key_hash FROM streamly_live_channels WHERE user_id=1").fetchone()[0]

def test_revoke_live_rejects_callback_even_for_retained_path(platform):
    import base64
    c,core,admin,setup,live=platform
    path="live_"+"b"*32
    with core.connect() as db:
        db.execute("INSERT INTO streamly_live_channels(user_id,path,key_hash,title) VALUES(1,?,?,'Live')",(path,live.digest("secret")))
    response=c.post("/internal/live-auth",json={"path":path,"user":"alice","password":"secret","action":"publish","protocol":"rtmp"},
                    headers={"authorization":"Basic "+base64.b64encode(("streamly:"+live.SECRET).encode()).decode()})
    assert response.status_code==403

def test_recommendations_and_filters_never_leak_pending_videos(platform):
    c,core,admin,setup,live=platform
    public=add_video(core,title="Public",state="approved")
    private=add_video(core,title="Hidden")
    assert [v["id"] for v in c.get("/?category=Gaming").json()["videos"]]==[public]
    assert not c.get("/?q=Hidden").json()["videos"]
    assert private not in [v["id"] for v in c.get(f"/watch/{public}").json()["recommended"]]

def test_failed_admin_login_rate_limit(platform):
    c,core,admin,setup,live=platform
    token=csrf(c)
    for i in range(9):
        response=c.post("/admin/login",data={"csrf":token,"password":"incorrect-admin-password"})
    assert response.status_code==429

def test_admin_session_expiry_forgery_and_reset(platform):
    c,core,admin,setup,live=platform
    admin_login(c)
    with core.connect() as db:
        db.execute("UPDATE streamly_admin_sessions SET expires_at=?",(core.now()-1,))
    assert c.get("/admin/users").status_code==401
    c.cookies.clear()
    c.cookies.set(admin.COOKIE,"forged-token")
    assert c.get("/admin/users").status_code==401
    admin_login(c)
    with core.connect() as db:
        setup.save_admin(db,"a-new-real-admin-password-2026",reset=True)
        assert db.execute("SELECT COUNT(*) FROM streamly_admin_sessions").fetchone()[0]==0
    assert c.get("/admin/users").status_code==401

def test_admin_html_escapes_titles_names_and_audit_details(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,title="<script>alert('x')</script>")
    token=admin_login(c)
    page=c.get("/admin").text
    assert "&lt;script&gt;" in page and "<script>alert" not in page
    c.post("/admin/users/1/update",data={"csrf":token,"action":"rename","display_name":"<b>Alice</b>"})
    assert "&lt;b&gt;Alice&lt;/b&gt;" in c.get("/admin/users").text
    assert "&lt;b&gt;" in c.get("/admin/audit").text

def test_creator_can_read_only_own_moderation_reasons(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,user_id=1)
    with core.connect() as db:
        db.execute("UPDATE streamly_video_moderation SET state='rejected',reason='Private reason for Alice' WHERE video_id=?",(vid,))
    owner(c,core,2)
    assert "Private reason for Alice" not in c.get("/studio/moderation").text
    owner(c,core,1)
    assert "Private reason for Alice" in c.get("/studio/moderation").text

def test_migration_keeps_old_videos_approved_and_new_pending(platform):
    c,core,admin,setup,live=platform
    old=add_video(core,state="approved")
    new=add_video(core)
    core.init_db()
    with core.connect() as db:
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(old,)).fetchone()[0]=="approved"
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(new,)).fetchone()[0]=="pending"

def test_moderation_states_constraints_and_invalid_actions(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    token=admin_login(c)
    assert c.post(f"/admin/videos/{vid}/moderate",data={"csrf":token,"state":"rejected","reason":""}).status_code==400
    assert c.post(f"/admin/videos/{vid}/moderate",data={"csrf":token,"state":"something"}).status_code==400
    assert c.post("/admin/users/1/update",data={"csrf":token,"action":"promote_me"}).status_code==400
    with core.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE streamly_video_moderation SET state='bypass'")

def test_installer_backups_idempotence_and_no_env_change(original_project):
    install=installer()
    env_before=(original_project/".env").read_bytes()
    backup=install.install(original_project)
    main=(original_project/"app/main.py").read_text()
    assert (backup/"files/app/main.py").exists()
    assert main.count("register_streamly_admin_guard(app)")==1
    assert 'public_video_clause("v")' in main
    install.install(original_project)
    assert (original_project/"app/main.py").read_text()==main
    assert (original_project/"app/schema.sql").read_text().count("-- STREAMLY_ADMIN_SCHEMA_V1")==1
    assert (original_project/".env").read_bytes()==env_before

def test_installer_refuses_unknown_recommendation_query_without_edits(original_project):
    install=installer()
    path=original_project/"app/main.py"
    text=path.read_text().replace('"WHERE v.id!=? ORDER BY (v.category=?) DESC,v.views DESC LIMIT 6"','"SELECT unrecognized"')
    path.write_text(text)
    with pytest.raises(ValueError):install.install(original_project)
    assert path.read_text()==text and not (original_project/"streamly-admin-backups").exists()

def test_no_stream_reenable_on_unblock(platform):
    c,core,admin,setup,live=platform
    token=admin_login(c)
    c.post("/admin/users/1/update",data={"csrf":token,"action":"allow_live"})
    c.post("/admin/users/1/update",data={"csrf":token,"action":"block","reason":"Test reason"})
    assert c.post("/admin/users/1/update",data={"csrf":token,"action":"allow_live"}).status_code==400
    c.post("/admin/users/1/update",data={"csrf":token,"action":"unblock"})
    with core.connect() as db:
        assert not admin.is_blocked(db,1) and not admin.may_stream(db,1)


def test_real_chunk_routes_publish_only_to_pending_queue(platform):
    c,core,admin,setup,live=platform
    token=owner(c,core)
    headers={"x-csrf-token":token}
    started=c.post("/api/uploads/init",json={"filename":"test.mp4","size":200,"title":"New upload","description":"","category":"Gaming"},headers=headers)
    assert started.status_code==200
    uid=started.json()["id"]
    assert c.put(f"/api/uploads/{uid}/chunks/0",content=b"x"*200,headers=headers).status_code==200
    assert c.post(f"/api/uploads/{uid}/finish",headers=headers).status_code==202
    status=c.get(f"/api/uploads/{uid}/status").json()
    assert status["state"]=="done"
    vid=status["video_id"]
    with core.connect() as db:
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]=="pending"
    assert c.get(f"/watch/{vid}").status_code==200
    c.cookies.clear()
    assert c.get(f"/watch/{vid}").status_code==404
    assert c.get(f"/media/{vid}").status_code==404

def test_normal_account_named_admin_is_not_an_administrator(platform):
    c,core,admin,setup,live=platform
    with core.connect() as db:
        db.execute("UPDATE users SET username='admin' WHERE id=1")
    token=owner(c,core)
    assert c.get("/admin",follow_redirects=False).status_code==303
    assert c.post("/admin/login",data={"csrf":token,"password":"normal-user-password-2026"}).status_code==400

def test_admin_cookie_is_secure_in_production(platform,monkeypatch):
    c,core,admin,setup,live=platform
    monkeypatch.setattr(core,"PRODUCTION",True)
    token=csrf(c)
    response=c.post("/admin/login",data={"csrf":token,"password":"a-real-test-admin-password-2026"},follow_redirects=False)
    assert response.status_code==303
    cookie=response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie

def test_admin_login_rotates_old_admin_session(platform):
    c,core,admin,setup,live=platform
    admin_login(c)
    old=next(x.value for x in c.cookies.jar if x.name==admin.COOKIE)
    admin_login(c)
    new=next(x.value for x in c.cookies.jar if x.name==admin.COOKIE)
    assert old!=new
    with core.connect() as db:
        assert not db.execute("SELECT 1 FROM streamly_admin_sessions WHERE token_hash=?",(admin.hashed(old),)).fetchone()
        assert db.execute("SELECT COUNT(*) FROM streamly_admin_sessions").fetchone()[0]==1

def test_all_relevant_metadata_changes_reset_approval(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,state="approved")
    with core.connect() as db:
        db.execute("UPDATE videos SET description='Changed description' WHERE id=?",(vid,))
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]=="pending"
        db.execute("UPDATE streamly_video_moderation SET state='approved' WHERE video_id=?",(vid,))
        db.execute("UPDATE videos SET category='Wissen' WHERE id=?",(vid,))
        assert db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(vid,)).fetchone()[0]=="pending"

def test_admin_audit_has_no_password_or_token_values(platform):
    c,core,admin,setup,live=platform
    admin_login(c)
    raw=next(x.value for x in c.cookies.jar if x.name==admin.COOKIE)
    with core.connect() as db:
        rows=db.execute("SELECT * FROM streamly_admin_audit").fetchall()
    serialized=json.dumps([dict(r) for r in rows])
    assert "a-real-test-admin-password-2026" not in serialized and raw not in serialized

def test_installer_also_supports_base_project_without_live_module(original_project):
    (original_project/"app/streamly_extension.py").unlink()
    # A base project does not have this prior import.
    path=original_project/"app/main.py"
    text=path.read_text().replace("from .streamly_extension import router as extension_router\napp.include_router(extension_router)","")
    path.write_text(text)
    install=installer()
    install.install(original_project)
    assert "register_streamly_admin_guard(app)" in path.read_text()
    schema=(original_project/"app/schema.sql").read_text()
    assert "UPDATE streamly_live_channels SET enabled=0,key_hash=''" not in schema


def test_missing_moderation_row_stays_fail_closed_even_after_restart(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core,state="approved")
    with core.connect() as db:
        db.execute("DELETE FROM streamly_video_moderation WHERE video_id=?",(vid,))
    core.init_db()
    assert c.get(f"/watch/{vid}").status_code==404
    assert not c.get("/").json()["videos"]

def test_schema_has_no_built_in_admin_account(platform):
    c,core,admin,setup,live=platform
    with core.connect() as db:
        db.execute("DELETE FROM streamly_admin_accounts")
    core.init_db()
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM streamly_admin_accounts").fetchone()[0]==0
    token=csrf(c)
    assert c.post("/admin/login",data={"csrf":token,"password":"12345678"}).status_code==400

def test_search_and_inputs_are_parameterized_and_audited_safely(platform):
    c,core,admin,setup,live=platform
    add_video(core)
    admin_login(c)
    assert c.get("/admin",params={"q":"' OR 1=1 --"}).status_code==200
    assert "A video" not in c.get("/admin",params={"q":"' OR 1=1 --"}).text
    assert c.get("/admin/users",params={"q":"' OR 1=1 --"}).status_code==200
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0]==2


def test_private_and_unknown_video_return_identical_guest_response(platform):
    c,core,admin,setup,live=platform
    vid=add_video(core)
    private=c.get(f"/watch/{vid}")
    unknown=c.get("/watch/"+"f"*32)
    assert private.status_code==unknown.status_code==404
    assert private.content==unknown.content
