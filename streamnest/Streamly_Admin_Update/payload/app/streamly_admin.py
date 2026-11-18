"""Manual moderation and a separately authenticated admin area."""
import hashlib
import json
import logging
import re
import secrets

from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from . import main as core

router = APIRouter()
COOKIE = "sl_admin_session"
ADMIN_TTL = 4 * 3600
log = logging.getLogger("streamly.admin")
DUMMY_HASH = core.ph.hash(secrets.token_urlsafe(32))

def hashed(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def public_creator_clause(alias="u"):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", alias):
        raise ValueError("Invalid SQL alias")
    return f"NOT EXISTS(SELECT 1 FROM streamly_user_safety us WHERE us.user_id={alias}.id AND us.blocked=1)"

def public_video_clause(alias="v"):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", alias):
        raise ValueError("Invalid SQL alias")
    return (
        f"EXISTS(SELECT 1 FROM streamly_video_moderation vm WHERE vm.video_id={alias}.id AND vm.state='approved') "
        f"AND NOT EXISTS(SELECT 1 FROM streamly_user_safety us WHERE us.user_id={alias}.user_id AND us.blocked=1)"
    )

def is_blocked(db, uid):
    return bool(db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=? AND blocked=1", (uid,)).fetchone())

def may_stream(db, uid):
    return bool(db.execute(
        "SELECT 1 FROM streamly_user_safety WHERE user_id=? AND blocked=0 AND can_stream=1", (uid,)).fetchone())

def assert_user_active(request):
    user = request.state.user
    if user and is_blocked(request.state.db, user["id"]):
        raise HTTPException(403, "Dieses Benutzerkonto ist gesperrt.")

def check_login_allowed(request, user_id):
    if is_blocked(request.state.db, user_id):
        raise HTTPException(403, "Dieses Benutzerkonto ist gesperrt.")

def assert_stream_allowed(request):
    user = core.require_user(request)
    if not may_stream(request.state.db, user["id"]):
        raise HTTPException(403, "Livestreaming muss zuerst von einem Administrator freigegeben werden.")
    return user

def admin_session(request, db):
    raw = request.cookies.get(COOKIE, "")
    if not raw or len(raw) > 128:
        return None
    return db.execute(
        "SELECT * FROM streamly_admin_sessions WHERE token_hash=? AND expires_at>?",
        (hashed(raw), core.now())).fetchone()

def require_admin(request):
    account = admin_session(request, request.state.db)
    if not account:
        raise HTTPException(401, "Bitte melde dich unter /admin/login als Administrator an.")
    return account

def regular_uid(request, db):
    raw = request.cookies.get(getattr(core, "COOKIE", "sn_session"), "")
    if not raw or len(raw) > 128:
        return None
    row = db.execute(
        "SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
        (hashed(raw), core.now())).fetchone()
    return row["user_id"] if row else None

def may_preview_video(request, db, video):
    if admin_session(request, db):
        return True
    uid = regular_uid(request, db)
    if uid and uid == video["user_id"]:
        return True
    state = db.execute(
        "SELECT state FROM streamly_video_moderation WHERE video_id=?", (video["id"],)).fetchone()
    return bool(state and state["state"] == "approved" and not is_blocked(db, video["user_id"]))

def register_media_guard(app):
    """Guard direct originals, posters, watch routes and view APIs before handlers."""
    @app.middleware("http")
    async def moderation_guard(request: Request, call_next):
        path = request.url.path
        video_match = re.match(r"^/(?:watch|media|poster)/([^/]+)(?:/|$)", path)
        api_match = re.fullmatch(r"/api/videos/([^/]+)/view", path)
        channel_match = re.match(r"^/channel/([^/]+)(?:/|$)", path)
        if video_match or api_match or channel_match:
            db = core.connect()
            denied = False
            try:
                if video_match or api_match:
                    vid = (video_match or api_match).group(1)
                    video = db.execute("SELECT id,user_id FROM videos WHERE id=?", (vid,)).fetchone()
                    if not video or not may_preview_video(request, db, video):
                        denied = True
                else:
                    creator = db.execute("SELECT id FROM users WHERE username=?", (channel_match.group(1),)).fetchone()
                    if not creator:
                        denied = True
                    elif is_blocked(db, creator["id"]):
                        denied = not (admin_session(request, db) or regular_uid(request, db) == creator["id"])
            finally:
                db.close()
            if denied:
                response = JSONResponse({"detail": "Nicht gefunden."}, status_code=404) if api_match else HTMLResponse(
                    "<!doctype html><html lang='de'><meta charset='utf-8'><title>Nicht verfügbar</title>"
                    "<h1>Dieser Inhalt ist nicht öffentlich verfügbar.</h1><p><a href='/'>Zur Startseite</a></p></html>",
                    status_code=404)
                response.headers["Cache-Control"] = "no-store"
                response.headers["Content-Security-Policy"] = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
        response = await call_next(request)
        if video_match or api_match:
            response.headers["Cache-Control"] = "no-store"
        return response

def audit(db, actor, action, target, details=""):
    db.execute(
        "INSERT INTO streamly_admin_audit(actor,action,target,details,created_at) VALUES(?,?,?,?,?)",
        (actor, action, str(target), str(details)[:3000], core.now()))

def admin_video(db, vid):
    row = db.execute(
        "SELECT v.*,u.username,u.display_name,m.state,m.reason FROM videos v JOIN users u ON u.id=v.user_id "
        "JOIN streamly_video_moderation m ON m.video_id=v.id WHERE v.id=?", (vid,)).fetchone()
    if not row:
        raise HTTPException(404, "Video nicht gefunden.")
    return row

def redirect(path):
    return core.redirect(path)

def render(request, name, **context):
    return core.render(request, name, **context)

@router.get("/admin/login")
def login_page(request: Request):
    return render(request, "streamly_admin_login.html", error="")

@router.post("/admin/login")
async def login(request: Request):
    async with request.form(max_files=0, max_fields=4) as form:
        core.csrf_check(request, form)
        core.rate(request, "admin_login_ip", 12, 900)
        core.rate(request, "admin_login_account", 8, 900, identity="admin")
        password = str(form.get("password", ""))
        if not 1 <= len(password) <= 128:
            raise HTTPException(400, "Anmeldung fehlgeschlagen.")
        db = request.state.db
        account = db.execute("SELECT * FROM streamly_admin_accounts WHERE username='admin'").fetchone()
        try:
            await run_in_threadpool(core.ph.verify, account["password_hash"] if account else DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            with db:
                audit(db, "anonymous", "admin_login_failed", "admin")
            response = render(request, "streamly_admin_login.html", error="Anmeldung fehlgeschlagen.")
            response.status_code = 400
            return response
        if not account:
            raise HTTPException(400, "Anmeldung fehlgeschlagen.")
        raw = secrets.token_urlsafe(32)
        with db:
            old = request.cookies.get(COOKIE, "")
            if old:
                db.execute("DELETE FROM streamly_admin_sessions WHERE token_hash=?", (hashed(old),))
            db.execute("DELETE FROM streamly_admin_sessions WHERE expires_at<?", (core.now(),))
            db.execute("INSERT INTO streamly_admin_sessions VALUES(?,?,?)",
                       (hashed(raw), "admin", core.now() + ADMIN_TTL))
            audit(db, "admin", "admin_login", "admin")
        response = redirect("/admin")
        response.set_cookie(COOKIE, raw, httponly=True, secure=core.PRODUCTION,
                            samesite="strict", max_age=ADMIN_TTL, path="/")
        return response

@router.post("/admin/logout")
async def logout(request: Request):
    require_admin(request)
    async with request.form(max_files=0, max_fields=2) as form:
        core.csrf_check(request, form)
        with request.state.db:
            request.state.db.execute("DELETE FROM streamly_admin_sessions WHERE token_hash=?",
                                     (hashed(request.cookies.get(COOKIE, "")),))
        response = redirect("/admin/login")
        response.delete_cookie(COOKIE, path="/", secure=core.PRODUCTION, httponly=True, samesite="strict")
        return response

@router.get("/admin")
def dashboard(request: Request, state: str = "pending", q: str = "", page: int = 1):
    if not admin_session(request, request.state.db):
        return redirect("/admin/login")
    db = request.state.db
    q = q.strip()[:100]
    page = max(1, min(page, 10000))
    state = state if state in ("pending", "approved", "rejected", "all") else "pending"
    conditions, args = [], []
    if state != "all":
        conditions.append("m.state=?"); args.append(state)
    if q:
        term = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append("(v.title LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\')")
        args.extend([term, term])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = db.execute(
        "SELECT v.*,u.username,u.display_name,m.state,m.reason FROM videos v "
        "JOIN users u ON u.id=v.user_id JOIN streamly_video_moderation m ON m.video_id=v.id" +
        where + " ORDER BY v.created_at DESC,v.id DESC LIMIT 41 OFFSET ?", (*args, (page-1)*40)).fetchall()
    counts = {row["state"]: row["n"] for row in db.execute(
        "SELECT state,COUNT(*) AS n FROM streamly_video_moderation GROUP BY state")}
    return render(request, "streamly_admin_dashboard.html", videos=rows[:40], more=len(rows)>40,
                  counts=counts, state=state, q=q, page=page)

@router.get("/admin/videos/{vid}")
def edit_page(request: Request, vid: str):
    require_admin(request)
    return render(request, "streamly_admin_video.html", video=admin_video(request.state.db, vid))

@router.post("/admin/videos/{vid}/edit")
async def edit_video(request: Request, vid: str):
    account = require_admin(request)
    async with request.form(max_files=0, max_fields=5) as form:
        core.csrf_check(request, form)
        title = core.field(form, "title", 3, 140)
        description = core.field(form, "description", 0, 5000)
        category = core.field(form, "category", 1, 40)
        if category not in core.CATEGORIES:
            raise HTTPException(400, "Ungültige Kategorie.")
        db = request.state.db
        video = admin_video(db, vid)
        with db:
            db.execute("UPDATE videos SET title=?,description=?,category=? WHERE id=?",
                       (title, description, category, vid))
            audit(db, account["username"], "video_edit", vid, json.dumps(
                {"old_title": video["title"], "new_title": title}, ensure_ascii=False))
    return redirect(f"/admin/videos/{vid}")

@router.post("/admin/videos/{vid}/moderate")
async def moderate_video(request: Request, vid: str):
    account = require_admin(request)
    async with request.form(max_files=0, max_fields=4) as form:
        core.csrf_check(request, form)
        state = str(form.get("state", ""))
        if state not in ("approved", "rejected", "pending"):
            raise HTTPException(400, "Ungültiger Prüfstatus.")
        reason = core.field(form, "reason", 3 if state == "rejected" else 0, 1000)
        db = request.state.db
        admin_video(db, vid)
        with db:
            db.execute(
                "UPDATE streamly_video_moderation SET state=?,reason=?,reviewer=?,updated_at=? WHERE video_id=?",
                (state, reason, account["username"], core.now(), vid))
            audit(db, account["username"], "video_" + state, vid, reason)
    return redirect("/admin")

@router.post("/admin/videos/{vid}/delete")
async def delete_video(request: Request, vid: str):
    account = require_admin(request)
    async with request.form(max_files=0, max_fields=2) as form:
        core.csrf_check(request, form)
        db = request.state.db
        video = admin_video(db, vid)
        with db:
            db.execute("DELETE FROM videos WHERE id=?", (vid,))
            audit(db, account["username"], "video_delete", vid, video["title"])
        for name in (video["filename"], video["poster"]):
            if not name:
                continue
            try:
                path = (core.MEDIA / name).resolve()
                if path.parent != core.MEDIA.resolve():
                    raise OSError("Unexpected media path")
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("Video %s removed from DB; media file cleanup failed.", vid)
                with db:
                    audit(db, account["username"], "file_cleanup_warning", vid)
    return redirect("/admin")

@router.get("/admin/users")
def users(request: Request, q: str = "", page: int = 1):
    require_admin(request)
    q = q.strip()[:100]; page = max(1, min(page, 10000))
    term = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = request.state.db.execute(
        "SELECT u.id,u.username,u.display_name,u.created_at,COALESCE(s.blocked,0) AS blocked,"
        "COALESCE(s.can_stream,0) AS can_stream,COALESCE(s.reason,'') AS reason,"
        "(SELECT COUNT(*) FROM videos WHERE user_id=u.id) AS video_count "
        "FROM users u LEFT JOIN streamly_user_safety s ON s.user_id=u.id "
        "WHERE u.username LIKE ? ESCAPE '\\' OR u.display_name LIKE ? ESCAPE '\\' "
        "ORDER BY u.created_at DESC,u.id DESC LIMIT 41 OFFSET ?",
        (term, term, (page-1)*40)).fetchall()
    return render(request, "streamly_admin_users.html", accounts=rows[:40], more=len(rows)>40, page=page, q=q)

def kick_creator(uid):
    try:
        from . import streamly_extension as live
        db = core.connect()
        try:
            row = db.execute("SELECT path FROM streamly_live_channels WHERE user_id=?", (uid,)).fetchone()
        finally:
            db.close()
        if row:
            live.kick_path(row["path"])
    except Exception:
        log.warning("Could not stop an RTMP connection for user %s; public playback remains blocked.", uid)

@router.post("/admin/users/{uid}/update")
async def update_user(request: Request, uid: int):
    account = require_admin(request)
    async with request.form(max_files=0, max_fields=6) as form:
        core.csrf_check(request, form)
        action = str(form.get("action", ""))
        db = request.state.db
        user = db.execute("SELECT id,username,display_name FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise HTTPException(404, "Konto nicht gefunden.")
        stop_live = False
        with db:
            db.execute(
                "INSERT OR IGNORE INTO streamly_user_safety(user_id,updated_at) VALUES(?,?)", (uid, core.now()))
            if action == "rename":
                name = core.field(form, "display_name", 2, 60)
                db.execute("UPDATE users SET display_name=? WHERE id=?", (name, uid))
                details = json.dumps({"before": user["display_name"], "after": name}, ensure_ascii=False)
            elif action == "block":
                reason = core.field(form, "reason", 3, 1000)
                db.execute("UPDATE streamly_user_safety SET blocked=1,can_stream=0,reason=?,updated_at=? WHERE user_id=?",
                           (reason, core.now(), uid))
                db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                stop_live = True; details = reason
            elif action == "unblock":
                db.execute("UPDATE streamly_user_safety SET blocked=0,reason='',updated_at=? WHERE user_id=?", (core.now(), uid))
                details = "Kontosperre aufgehoben; Livestreaming bleibt separat freizugeben."
            elif action == "allow_live":
                if is_blocked(db, uid):
                    raise HTTPException(400, "Ein gesperrtes Konto darf nicht live gehen.")
                db.execute("UPDATE streamly_user_safety SET can_stream=1,updated_at=? WHERE user_id=?", (core.now(), uid))
                details = "Livestreaming freigegeben."
            elif action == "deny_live":
                db.execute("UPDATE streamly_user_safety SET can_stream=0,updated_at=? WHERE user_id=?", (core.now(), uid))
                stop_live = True; details = "Livestreaming gesperrt."
            else:
                raise HTTPException(400, "Ungültige Aktion.")
            if stop_live and db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='streamly_live_channels'").fetchone():
                db.execute("UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE user_id=?", (uid,))
            audit(db, account["username"], "user_" + action, uid, details)
        if stop_live:
            await run_in_threadpool(kick_creator, uid)
    return redirect("/admin/users")

@router.get("/admin/audit")
def audit_page(request: Request, page: int = 1):
    require_admin(request)
    page = max(1, min(page, 10000))
    rows = request.state.db.execute(
        "SELECT * FROM streamly_admin_audit ORDER BY id DESC LIMIT 101 OFFSET ?", ((page-1)*100,)).fetchall()
    return render(request, "streamly_admin_audit.html", events=rows[:100], page=page, more=len(rows)>100)

@router.get("/studio/moderation")
def creator_moderation(request: Request):
    user = core.require_user(request)
    videos = request.state.db.execute(
        "SELECT v.id,v.title,v.created_at,m.state,m.reason FROM videos v JOIN streamly_video_moderation m "
        "ON m.video_id=v.id WHERE v.user_id=? ORDER BY v.created_at DESC LIMIT 200", (user["id"],)).fetchall()
    return render(request, "streamly_creator_moderation.html", videos=videos)
