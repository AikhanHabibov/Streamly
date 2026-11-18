"""MFA and authenticated abuse reporting for the existing Streamly admin update."""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from . import main as core

router = APIRouter()
log = logging.getLogger("streamly.security")
CHALLENGE_COOKIE = "sl_admin_challenge"
CHALLENGE_TTL = 300
MAX_OTP_ATTEMPTS = 5
REPORT_CATEGORIES = [
    "Belästigung / Hass", "Gewalt / gefährliche Inhalte", "Sexuelle Inhalte",
    "Spam / Betrug", "Urheberrecht", "Private Daten", "Sonstiges"
]
REPORT_STATUSES = {"open", "reviewing", "resolved", "dismissed"}

def admin_module():
    from . import streamly_admin
    return streamly_admin

def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def key_path():
    return Path(os.getenv("STREAMLY_MFA_KEY_FILE", str(core.DATA / "secrets" / "admin_mfa.key")))

def cipher():
    try:
        return Fernet(key_path().read_bytes().strip())
    except (OSError, ValueError):
        raise HTTPException(503, "Der MFA-Schlüssel ist nicht verfügbar. Server-Schlüssel aus dem Backup wiederherstellen oder MFA im Terminal neu einrichten.")

def totp(secret, timestamp, digits=6):
    counter = int(timestamp) // 30
    if counter < 0:
        raise ValueError("Negative timestamp")
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 15
    number = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7fffffff
    return str(number % (10 ** digits)).zfill(digits)

def match_counter(secret, code, timestamp, last_counter=-1):
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    current = int(timestamp) // 30
    matches = [current + delta for delta in (-1, 0, 1)
               if current + delta >= 0 and current + delta > last_counter
               and secrets.compare_digest(totp(secret, (current + delta) * 30), code)]
    return max(matches) if matches else None

def normalize_recovery(value):
    return value.replace("-", "").replace(" ", "").strip().upper()

def recovery_hash(username, code):
    return sha("streamly-recovery-v1:" + username + ":" + normalize_recovery(code))

def admin_session_ok(request, db):
    """A legacy/password-only admin cookie must never become a full MFA session."""
    adm = admin_module()
    raw = request.cookies.get(adm.COOKIE, "")
    if not raw or len(raw) > 128:
        return False
    return bool(db.execute(
        "SELECT 1 FROM streamly_admin_sessions s JOIN streamly_mfa_sessions v ON v.token_hash=s.token_hash "
        "JOIN streamly_mfa m ON m.username=s.username "
        "WHERE s.token_hash=? AND s.expires_at>? AND m.enabled=1 AND v.generation=m.generation",
        (sha(raw), core.now())).fetchone())

def begin_admin_mfa(request, db, account):
    """Called only after the existing password check. Does not grant admin rights."""
    cfg = db.execute("SELECT * FROM streamly_mfa WHERE username=? AND enabled=1", (account["username"],)).fetchone()
    if not cfg:
        raise HTTPException(503, "Zwei-Faktor-Anmeldung ist noch nicht eingerichtet. Bitte im Server-Terminal python -m app.streamly_security_setup ausführen.")
    raw = secrets.token_urlsafe(32)
    adm = admin_module()
    with db:
        old = request.cookies.get(CHALLENGE_COOKIE, "")
        if old:
            db.execute("DELETE FROM streamly_mfa_challenges WHERE token_hash=?", (sha(old),))
        prior = request.cookies.get(adm.COOKIE, "")
        if prior:
            db.execute("DELETE FROM streamly_admin_sessions WHERE token_hash=?", (sha(prior),))
        db.execute("DELETE FROM streamly_mfa_challenges WHERE expires_at<?", (core.now(),))
        db.execute("DELETE FROM streamly_admin_sessions WHERE expires_at<?", (core.now(),))
        db.execute(
            "INSERT INTO streamly_mfa_challenges(token_hash,username,generation,password_version,expires_at) VALUES(?,?,?,?,?)",
            (sha(raw), account["username"], cfg["generation"], sha(account["password_hash"]), core.now() + CHALLENGE_TTL))
        adm.audit(db, account["username"], "admin_password_accepted", "admin")
    response = core.redirect("/admin/mfa")
    response.delete_cookie(adm.COOKIE, path="/", secure=core.PRODUCTION, httponly=True, samesite="strict")
    response.set_cookie(CHALLENGE_COOKIE, raw, max_age=CHALLENGE_TTL, secure=core.PRODUCTION,
                        httponly=True, samesite="strict", path="/admin")
    return response

def challenge_row(request, db):
    raw = request.cookies.get(CHALLENGE_COOKIE, "")
    if not raw or len(raw) > 128:
        return None
    return db.execute(
        "SELECT c.*,m.secret_cipher,m.last_counter,m.enabled,a.password_hash,m.generation AS current_generation "
        "FROM streamly_mfa_challenges c JOIN streamly_mfa m ON m.username=c.username "
        "JOIN streamly_admin_accounts a ON a.username=c.username WHERE c.token_hash=?",
        (sha(raw),)).fetchone()

def valid_challenge(row):
    return bool(row and row["enabled"] and row["expires_at"] > core.now()
                and row["attempts"] < MAX_OTP_ATTEMPTS
                and row["generation"] == row["current_generation"]
                and secrets.compare_digest(row["password_version"], sha(row["password_hash"])))

@router.get("/admin/mfa")
def mfa_page(request: Request):
    row = challenge_row(request, request.state.db)
    if not valid_challenge(row):
        response = core.redirect("/admin/login")
        response.delete_cookie(CHALLENGE_COOKIE, path="/admin", secure=core.PRODUCTION, httponly=True, samesite="strict")
        return response
    return core.render(request, "streamly_mfa.html", error="")

@router.post("/admin/mfa")
async def verify_mfa(request: Request):
    async with request.form(max_files=0, max_fields=3) as form:
        core.csrf_check(request, form)
        core.rate(request, "admin_mfa_ip", 20, 300)
        code = str(form.get("code", "")).strip()
        if len(code) > 64:
            code = ""
        db = request.state.db
        adm = admin_module()
        raw_session = None
        # One transaction serializes challenge attempts, TOTP replay checks and recovery consumption.
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = challenge_row(request, db)
            if not valid_challenge(row):
                return core.redirect("/admin/login")
            db.execute("UPDATE streamly_mfa_challenges SET attempts=attempts+1 WHERE token_hash=?", (row["token_hash"],))
            method = ""
            counter = None
            normalized = normalize_recovery(code)
            if re.fullmatch(r"[A-F0-9]{32}", normalized):
                consumed = db.execute(
                    "UPDATE streamly_mfa_recovery SET used_at=? WHERE username=? AND code_hash=? AND used_at IS NULL",
                    (core.now(), row["username"], recovery_hash(row["username"], normalized))).rowcount
                if consumed:
                    method = "recovery"
            elif re.fullmatch(r"[0-9]{6}", code):
                try:
                    seed = cipher().decrypt(row["secret_cipher"].encode()).decode("ascii")
                except (InvalidToken, UnicodeError):
                    raise HTTPException(503, "MFA-Daten konnten nicht entschlüsselt werden. Bitte den Betreiber kontaktieren.")
                counter = match_counter(seed, code, core.now(), row["last_counter"])
                if counter is not None:
                    method = "totp"
            if not method:
                adm.audit(db, row["username"], "admin_mfa_failed", "admin")
                response = core.render(request, "streamly_mfa.html",
                    error="Code ungültig oder bereits verwendet. Nach fünf Versuchen bitte erneut mit dem Passwort anmelden.")
                response.status_code = 400
                return response
            if counter is not None:
                db.execute("UPDATE streamly_mfa SET last_counter=? WHERE username=?", (counter, row["username"]))
            raw_session = secrets.token_urlsafe(32)
            token = sha(raw_session)
            db.execute("INSERT INTO streamly_admin_sessions VALUES(?,?,?)",
                       (token, row["username"], core.now() + adm.ADMIN_TTL))
            db.execute("INSERT INTO streamly_mfa_sessions VALUES(?,?,?,?)",
                       (token, row["generation"], method, core.now()))
            db.execute("DELETE FROM streamly_mfa_challenges WHERE token_hash=?", (row["token_hash"],))
            adm.audit(db, row["username"], "admin_login_mfa", "admin", method)
        response = core.redirect("/admin")
        response.set_cookie(adm.COOKIE, raw_session, httponly=True, secure=core.PRODUCTION,
                            samesite="strict", max_age=adm.ADMIN_TTL, path="/")
        response.delete_cookie(CHALLENGE_COOKIE, path="/admin", secure=core.PRODUCTION, httponly=True, samesite="strict")
        return response

@router.get("/admin/security")
def security_page(request: Request):
    adm = admin_module()
    account = adm.require_admin(request)
    db = request.state.db
    cfg = db.execute("SELECT configured_at FROM streamly_mfa WHERE username=?", (account["username"],)).fetchone()
    remaining = db.execute(
        "SELECT COUNT(*) FROM streamly_mfa_recovery WHERE username=? AND used_at IS NULL", (account["username"],)).fetchone()[0]
    verified = db.execute("SELECT method FROM streamly_mfa_sessions WHERE token_hash=?", (account["token_hash"],)).fetchone()
    return core.render(request, "streamly_admin_security.html", configured_at=cfg["configured_at"],
                       remaining=remaining, recovery_login=bool(verified and verified["method"] == "recovery"))

def table_exists(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

def target_info(request, kind, target_id, visible=True):
    db = request.state.db
    adm = admin_module()
    if kind == "video":
        row = db.execute(
            "SELECT v.*,u.username FROM videos v JOIN users u ON u.id=v.user_id WHERE v.id=?", (target_id,)).fetchone()
        if not row or (visible and not adm.may_preview_video(request, db, row)):
            raise HTTPException(404, "Inhalt nicht verfügbar.")
        info = {"kind":kind,"id":str(row["id"]),"owner_id":row["user_id"],"owner_name":row["username"],
                "title":row["title"],"snapshot":row["description"][:1000],"video_id":row["id"],
                "version_data":[row["filename"],row["title"],row["description"],row["created_at"]]}
    elif kind == "comment" and re.fullmatch(r"[0-9]{1,15}", target_id):
        row = db.execute(
            "SELECT c.*,v.user_id AS video_owner,v.title,u.username FROM comments c JOIN videos v ON v.id=c.video_id "
            "JOIN users u ON u.id=c.user_id WHERE c.id=?", (int(target_id),)).fetchone()
        if not row or (visible and not adm.may_preview_video(request, db, {"id":row["video_id"],"user_id":row["video_owner"]})):
            raise HTTPException(404, "Inhalt nicht verfügbar.")
        info = {"kind":kind,"id":str(row["id"]),"owner_id":row["user_id"],"owner_name":row["username"],
                "title":"Kommentar zu: "+row["title"],"snapshot":row["body"][:1000],"video_id":row["video_id"],
                "version_data":[row["body"],row["created_at"],row["video_id"]]}
    elif kind == "live" and re.fullmatch(r"[a-z0-9_]{3,30}", target_id) and table_exists(db,"streamly_live_channels"):
        row = db.execute(
            "SELECT s.*,u.username FROM streamly_live_channels s JOIN users u ON u.id=s.user_id WHERE u.username=?",
            (target_id,)).fetchone()
        if not row or (visible and (not row["enabled"] or not row["key_hash"] or not adm.may_stream(db,row["user_id"]))):
            raise HTTPException(404, "Inhalt nicht verfügbar.")
        info = {"kind":kind,"id":row["username"],"owner_id":row["user_id"],"owner_name":row["username"],
                "title":row["title"],"snapshot":row["description"][:1000],"video_id":"",
                "version_data":[row["path"],row["title"],row["description"]]}
    else:
        raise HTTPException(404, "Inhalt nicht verfügbar.")
    info["version"] = sha(json.dumps([kind,info["id"],info["owner_id"],info["version_data"]],ensure_ascii=False))
    return info

@router.get("/report/{kind}/{target_id}")
def report_form(request: Request, kind: str, target_id: str):
    core.require_user(request)
    target = target_info(request, kind, target_id)
    return core.render(request, "streamly_report.html", target=target, report_categories=REPORT_CATEGORIES)

@router.post("/report/{kind}/{target_id}")
async def submit_report(request: Request, kind: str, target_id: str):
    user = core.require_user(request)
    async with request.form(max_files=0, max_fields=5) as form:
        core.csrf_check(request, form)
        core.rate(request, "reports_user", 10, 3600, identity=str(user["id"]))
        core.rate(request, "reports_ip", 60, 3600)
        category = core.field(form, "category", 1, 60)
        reason = core.field(form, "reason", 10, 2000)
        if category not in REPORT_CATEGORIES:
            raise HTTPException(400, "Ungültiger Meldegrund.")
        db = request.state.db
        with db:
            db.execute("BEGIN IMMEDIATE")
            target = target_info(request, kind, target_id)
            if not secrets.compare_digest(str(form.get("version","")).encode(), target["version"].encode()):
                raise HTTPException(409, "Der Inhalt wurde inzwischen geändert. Bitte die Meldeseite neu öffnen.")
            db.execute("INSERT OR IGNORE INTO streamly_security_identities VALUES(?,?)",
                       (target["owner_id"],secrets.token_hex(16)))
            owner_identity = db.execute("SELECT identity FROM streamly_security_identities WHERE user_id=?",
                                        (target["owner_id"],)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO streamly_security_content_ids VALUES(?,?,?)",
                       (kind,target["id"],secrets.token_hex(16)))
            nonce = db.execute("SELECT nonce FROM streamly_security_content_ids WHERE target_type=? AND target_id=?",
                               (kind,target["id"])).fetchone()[0]
            old = db.execute(
                "SELECT id FROM streamly_reports WHERE reporter_id=? AND target_type=? AND target_id=? AND target_nonce=? "
                "AND status IN ('open','reviewing')",
                (user["id"],kind,target["id"],nonce)).fetchone()
            if old:
                return core.redirect("/reports/mine?duplicate=1")
            db.execute(
                "INSERT INTO streamly_reports(reporter_id,target_type,target_id,target_nonce,target_owner_id,owner_identity,"
                "owner_name,target_title,snapshot,category,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user["id"],kind,target["id"],nonce,target["owner_id"],owner_identity,target["owner_name"],
                 target["title"][:200],target["snapshot"],category,reason,core.now(),core.now()))
    return core.redirect("/reports/mine?sent=1")

@router.get("/reports/mine")
def my_reports(request: Request):
    user = core.require_user(request)
    reports = request.state.db.execute(
        "SELECT id,target_type,target_title,category,reason,status,created_at FROM streamly_reports "
        "WHERE reporter_id=? ORDER BY id DESC LIMIT 50", (user["id"],)).fetchall()
    return core.render(request, "streamly_my_reports.html", reports=reports)

@router.get("/admin/reports")
def report_queue(request: Request, status: str = "open", page: int = 1):
    admin_module().require_admin(request)
    status = status if status in REPORT_STATUSES or status == "all" else "open"
    page = max(1,min(page,10000))
    rows = request.state.db.execute(
        "SELECT r.*,u.username AS reporter FROM streamly_reports r LEFT JOIN users u ON u.id=r.reporter_id " +
        ("WHERE r.status=? " if status != "all" else "") +
        "ORDER BY r.created_at DESC,r.id DESC LIMIT 41 OFFSET ?",
        ((status,(page-1)*40) if status != "all" else ((page-1)*40,))).fetchall()
    return core.render(request,"streamly_report_queue.html",reports=rows[:40],more=len(rows)>40,page=page,status=status)

def load_report(db, report_id):
    row = db.execute("SELECT * FROM streamly_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Meldung nicht gefunden.")
    return row

def current_owner(db, report):
    return db.execute(
        "SELECT u.id,u.username FROM users u JOIN streamly_security_identities i ON i.user_id=u.id "
        "WHERE u.id=? AND i.identity=?", (report["target_owner_id"],report["owner_identity"])).fetchone()

def current_target(request, report):
    row = request.state.db.execute(
        "SELECT nonce FROM streamly_security_content_ids WHERE target_type=? AND target_id=?",
        (report["target_type"],report["target_id"])).fetchone()
    if not row or not secrets.compare_digest(row["nonce"],report["target_nonce"]) or not current_owner(request.state.db,report):
        return None
    try:
        info = target_info(request,report["target_type"],report["target_id"],visible=False)
    except HTTPException:
        return None
    return info if info["owner_id"] == report["target_owner_id"] else None

@router.get("/admin/reports/{report_id}")
def report_detail(request: Request, report_id: int):
    admin_module().require_admin(request)
    report = load_report(request.state.db,report_id)
    info = current_target(request,report)
    return core.render(request,"streamly_report_detail.html",report=report,
                       target_available=bool(info),owner_available=bool(current_owner(request.state.db,report)),
                       target_video=info["video_id"] if info else "")

def remove_media_files(video, adm, db, actor):
    for name in (video["filename"],video["poster"]):
        if name:
            try:
                path=(core.MEDIA/name).resolve()
                if path.parent != core.MEDIA.resolve():
                    raise OSError("Unexpected media path")
                path.unlink(missing_ok=True)
            except OSError:
                with db:
                    adm.audit(db,actor,"file_cleanup_warning",video["id"])
                log.warning("Media cleanup failed for video %s",video["id"])

@router.post("/admin/reports/{report_id}/action")
async def handle_report(request: Request, report_id: int):
    adm=admin_module()
    account=adm.require_admin(request)
    removed_video=None;stop_uid=None
    async with request.form(max_files=0,max_fields=4) as form:
        core.csrf_check(request,form)
        action=str(form.get("action",""))
        note=core.field(form,"note",0,2000)
        allowed={"reviewing","dismissed","resolved","remove_video","remove_comment","stop_live","block_account"}
        if action not in allowed:
            raise HTTPException(400,"Ungültige Aktion.")
        db=request.state.db
        with db:
            db.execute("BEGIN IMMEDIATE")
            report=load_report(db,report_id)
            if action in {"remove_video","remove_comment","stop_live"}:
                expected={"remove_video":"video","remove_comment":"comment","stop_live":"live"}[action]
                if report["target_type"]!=expected:
                    raise HTTPException(400,"Diese Aktion passt nicht zur Meldung.")
                info=current_target(request,report)
                if not info:
                    raise HTTPException(409,"Der ursprüngliche Inhalt ist nicht mehr vorhanden. Keine andere Datei wurde verändert.")
                if action=="remove_video":
                    removed_video=db.execute("SELECT * FROM videos WHERE id=?",(report["target_id"],)).fetchone()
                    db.execute("DELETE FROM videos WHERE id=?",(report["target_id"],))
                elif action=="remove_comment":
                    db.execute("DELETE FROM comments WHERE id=?",(int(report["target_id"]),))
                else:
                    stop_uid=info["owner_id"]
                    db.execute(
                        "INSERT INTO streamly_user_safety(user_id,can_stream,updated_at) VALUES(?,0,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET can_stream=0,updated_at=excluded.updated_at",(stop_uid,core.now()))
                    db.execute("UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE user_id=?",(stop_uid,))
                status="resolved"
            elif action=="block_account":
                owner=current_owner(db,report)
                if not owner:
                    raise HTTPException(409,"Das ursprüngliche Konto existiert nicht mehr. Kein anderes Konto wurde gesperrt.")
                stop_uid=owner["id"]
                reason=note or f"Moderation zu Meldung #{report_id}"
                db.execute(
                    "INSERT INTO streamly_user_safety(user_id,blocked,can_stream,reason,updated_at) VALUES(?,1,0,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET blocked=1,can_stream=0,reason=excluded.reason,updated_at=excluded.updated_at",
                    (stop_uid,reason,core.now()))
                db.execute("DELETE FROM sessions WHERE user_id=?",(stop_uid,))
                if table_exists(db,"streamly_live_channels"):
                    db.execute("UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE user_id=?",(stop_uid,))
                status="resolved"
            else:
                status=action
            if status == "reviewing" and report["reporter_id"] is not None:
                duplicate=db.execute(
                    "SELECT 1 FROM streamly_reports WHERE id!=? AND reporter_id=? AND target_type=? AND target_id=? AND target_nonce=? "
                    "AND status IN ('open','reviewing')",
                    (report_id,report["reporter_id"],report["target_type"],report["target_id"],report["target_nonce"])).fetchone()
                if duplicate:
                    raise HTTPException(409,"Für diesen Nutzer und Inhalt gibt es bereits eine offene Meldung.")
            db.execute("UPDATE streamly_reports SET status=?,admin_note=?,handled_by=?,updated_at=? WHERE id=?",
                       (status,note,account["username"],core.now(),report_id))
            adm.audit(db,account["username"],"report_"+action,report_id,note)
        if removed_video:
            remove_media_files(removed_video,adm,db,account["username"])
        if stop_uid is not None:
            await run_in_threadpool(adm.kick_creator,stop_uid)
    return core.redirect(f"/admin/reports/{report_id}")
