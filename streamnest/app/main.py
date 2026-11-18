"""Streamly: server-rendered, single-server video platform."""
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", str(BASE.parent / "data"))).resolve()
MEDIA = DATA / "media"
DATABASE = DATA / "streamnest.sqlite3"
PRODUCTION = os.getenv("APP_ENV") == "production"
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_MB", "2048")) * 1024 * 1024
MAX_USER_BYTES = int(os.getenv("USER_QUOTA_MB", "20480")) * 1024 * 1024
COOKIE = "sn_session"
SESSION_TTL = 7 * 86400
CATEGORIES = ["Gaming", "Technologie", "Musik", "Kreativ", "Wissen", "Lifestyle"]
ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = ph.hash(secrets.token_urlsafe(24))
templates = Jinja2Templates(directory=str(BASE / "templates"))

def now():
    return int(time.time())

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db

def init_db():
    MEDIA.mkdir(parents=True, exist_ok=True)
    db = connect()
    try:
        with db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript((BASE / "schema.sql").read_text())
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app):
    if PRODUCTION and not PUBLIC_URL.startswith("https://"):
        raise RuntimeError("Produktion benötigt PUBLIC_URL=https://deine-domain.ch")
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg und ffprobe fehlen. Siehe README.")
    init_db()
    yield

app = FastAPI(title="Streamly", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[urlsplit(PUBLIC_URL).hostname, "web"] if PRODUCTION else ["localhost", "127.0.0.1", "testserver", "web"],
)

class BodyLimit:
    """Limit even chunked request bodies before multipart parsing fills the disk."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        limit = MAX_VIDEO_BYTES + 2 * 1024 * 1024 if scope["path"] == "/upload" else 128 * 1024
        if scope["path"].startswith("/api/uploads/") and "/chunks/" in scope["path"]:
            limit = 9 * 1024 * 1024
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await JSONResponse({"detail": "Datei oder Anfrage zu gross."}, status_code=413)(scope, receive, send)
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise StarletteHTTPException(413, "Datei oder Anfrage zu gross.")
            return message
        await self.app(scope, limited_receive, send)

app.add_middleware(BodyLimit)

def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

def rotate_session(request, user_id=None):
    db = request.state.db
    old = getattr(request.state, "session", None)
    raw = secrets.token_urlsafe(32)
    session = {"token_hash": token_hash(raw), "csrf": secrets.token_urlsafe(32),
               "user_id": user_id, "expires_at": now() + SESSION_TTL}
    with db:
        if old:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (old["token_hash"],))
        db.execute("INSERT INTO sessions VALUES(:token_hash,:csrf,:user_id,:expires_at)", session)
    request.state.session = session
    request.state.cookie = raw

@app.middleware("http")
async def session_and_headers(request: Request, call_next):
    if request.url.path.startswith("/static/"):
        response = await call_next(request)
    else:
        db = connect()
        request.state.db = db
        request.state.cookie = None
        raw = request.cookies.get(COOKIE, "")
        session = db.execute(
            "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
            (token_hash(raw), now())
        ).fetchone() if raw and len(raw) < 128 else None
        request.state.session = dict(session) if session else None
        # Static assets, media and health checks must not create anonymous sessions.
        needs_session = not request.url.path.startswith(("/media/", "/poster/", "/health", "/hls/", "/internal/live-auth"))
        if not session and needs_session:
            rotate_session(request)
        request.state.user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone() if session and session["user_id"] else None
        try:
            response = await call_next(request)
            if request.state.cookie:
                response.set_cookie(COOKIE, request.state.cookie, max_age=SESSION_TTL,
                                    httponly=True, secure=PRODUCTION, samesite="lax", path="/")
            if secrets.randbelow(100) == 0:
                with db:
                    db.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
                    db.execute("DELETE FROM rate_limits WHERE expires_at<?", (now(),))
                    db.execute("DELETE FROM view_events WHERE day<?", (now() // 86400 - 30,))
        finally:
            db.close()
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store" if needs_session else "private, max-age=300")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

def render(request, name, **context):
    return templates.TemplateResponse(request=request, name=name, context={
        "user": request.state.user, "csrf": request.state.session["csrf"] if request.state.session else "",
        "categories": CATEGORIES, "path": request.url.path, "q": request.query_params.get("q", ""),
        "active_category": request.query_params.get("category", ""),
        **context
    })

@app.exception_handler(StarletteHTTPException)
async def errors(request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if not hasattr(request.state, "user"):
        return HTMLResponse("Anfrage abgelehnt.", status_code=exc.status_code)
    response = render(request, "error.html", status=exc.status_code, detail=exc.detail)
    response.status_code = exc.status_code
    return response

def require_user(request):
    admin_assert_user_active(request)
    if not request.state.user:
        raise HTTPException(401, "Bitte melde dich zuerst an.")
    return request.state.user

def csrf_check(request, form=None):
    session = request.state.session
    supplied = request.headers.get("x-csrf-token", "") if form is None else str(form.get("csrf", ""))
    if not session or not secrets.compare_digest(supplied.encode("utf-8"), session["csrf"].encode("utf-8")):
        raise HTTPException(403, "Sicherheitsprüfung fehlgeschlagen. Bitte lade die Seite neu.")
    origin = request.headers.get("origin")
    expected = PUBLIC_URL if PRODUCTION else str(request.base_url).rstrip("/")
    if origin and origin != expected:
        raise HTTPException(403, "Diese Anfrage stammt von einer fremden Webseite.")

def rate(request, action, maximum, window=900, identity=None):
    db = request.state.db
    # No X-Forwarded-For trust here: only Uvicorn may trust an explicitly configured proxy.
    identity = identity or (request.client.host if request.client else "unknown")
    key = token_hash(f"{action}:{identity}:{now() // window}")
    with db:
        db.execute(
            "INSERT INTO rate_limits(key,count,expires_at) VALUES(?,1,?) "
            "ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now() + window * 2))
        count = db.execute("SELECT count FROM rate_limits WHERE key=?", (key,)).fetchone()[0]
    if count > maximum:
        raise HTTPException(429, "Zu viele Versuche. Bitte versuche es später erneut.")

def field(form, name, low, high):
    value = str(form.get(name, "")).strip()
    if not low <= len(value) <= high:
        raise HTTPException(400, f"Das Feld «{name}» benötigt {low}–{high} Zeichen.")
    return value

def redirect(path):
    return RedirectResponse(path, status_code=303)

def video_or_404(db, vid):
    video = db.execute(
        "SELECT v.*,u.username,u.display_name,"
        "(SELECT COUNT(*) FROM likes WHERE video_id=v.id) AS likes "
        "FROM videos v JOIN users u ON u.id=v.user_id WHERE v.id=?", (vid,)).fetchone()
    if not video:
        raise HTTPException(404, "Dieses Video wurde nicht gefunden.")
    return video

VIDEO_QUERY = (
    "SELECT v.*,u.username,u.display_name,"
    "(SELECT COUNT(*) FROM likes WHERE video_id=v.id) AS likes "
    "FROM videos v JOIN users u ON u.id=v.user_id "
)

def get_videos(db, where="", args=(), order="v.created_at DESC", page=1, size=12):
    where = (where + " AND " if where else "WHERE ") + "(" + public_video_clause("v") + ")"
    rows = db.execute(VIDEO_QUERY + where + f" ORDER BY {order},v.id DESC LIMIT ? OFFSET ?",
                      (*args, size + 1, (page - 1) * size)).fetchall()
    return rows[:size], len(rows) > size

def template_filter(name):
    def register(func):
        templates.env.filters[name] = func
        return func
    return register

@template_filter("compact")
def compact(value):
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} Mio."
    if value >= 1000:
        return f"{value / 1000:.1f} Tsd."
    return str(value)

@template_filter("duration")
def duration(value):
    seconds = int(value or 0)
    return f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02}"

@template_filter("ago")
def ago(value):
    diff = max(0, now() - value)
    for unit, size in [("Jahren", 31536000), ("Monaten", 2592000), ("Tagen", 86400), ("Std.", 3600), ("Min.", 60)]:
        if diff >= size:
            return f"vor {diff // size} {unit}"
    return "gerade eben"

@app.get("/health")
def health(request: Request):
    request.state.db.execute("SELECT 1").fetchone()
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = "", sort: str = "new", page: int = 1):
    db = request.state.db
    page = max(1, min(page, 10000))
    q = q.strip()[:100]
    conditions, args = [], []
    if q:
        conditions.append("(v.title LIKE ? ESCAPE '\\' OR v.description LIKE ? ESCAPE '\\' OR u.display_name LIKE ? ESCAPE '\\' OR v.category LIKE ? ESCAPE '\\')")
        term = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args.extend([term] * 4)
    if category in CATEGORIES:
        conditions.append("v.category=?")
        args.append(category)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    videos, more = get_videos(db, where, args, "v.views DESC" if sort == "popular" else "v.created_at DESC", page)
    creators = db.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM subscriptions WHERE creator_id=u.id) AS subscribers "
        "FROM users u WHERE (u.username LIKE ? OR u.display_name LIKE ?) AND " + public_creator_clause("u") + " LIMIT 8",
        (f"%{q}%", f"%{q}%")).fetchall() if q else []
    return render(request, "home.html", videos=videos, creators=creators, page=page, more=more,
                  sort=sort, q=q, active_category=category, is_feed=False,
                  paging=f"/?q={quote(q)}&category={quote(category)}&sort={quote(sort)}&page=")

@app.get("/subscriptions", response_class=HTMLResponse)
def feed(request: Request, page: int = 1):
    user = require_user(request)
    page = max(1, min(page, 10000))
    videos, more = get_videos(request.state.db,
        "WHERE v.user_id IN (SELECT creator_id FROM subscriptions WHERE subscriber_id=?)",
        (user["id"],), page=page)
    return render(request, "home.html", videos=videos, creators=[], page=page, more=more,
                  sort="new", is_feed=True, paging="/subscriptions?page=")

@app.get("/register")
def register_page(request: Request):
    return render(request, "auth.html", mode="register")

@app.get("/login")
def login_page(request: Request):
    return render(request, "auth.html", mode="login")

@app.post("/register")
async def register(request: Request):
    async with request.form(max_files=0, max_fields=10) as form:
        csrf_check(request, form)
        rate(request, "register", 5, 3600)
        username = field(form, "username", 3, 30).lower()
        if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
            raise HTTPException(400, "Benutzername: nur a–z, Zahlen und Unterstriche.")
        display_name = field(form, "display_name", 2, 60)
        email = field(form, "email", 5, 254).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(400, "Bitte gib eine gültige E-Mail-Adresse ein.")
        password = str(form.get("password", ""))
        if not 12 <= len(password) <= 128:
            raise HTTPException(400, "Das Passwort muss 12–128 Zeichen enthalten.")
        hashed = await run_in_threadpool(ph.hash, password)
        db = request.state.db
        try:
            with db:
                uid = db.execute(
                    "INSERT INTO users(username,email,password_hash,display_name,created_at) VALUES(?,?,?,?,?)",
                    (username, email, hashed, display_name, now())).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Dieser Benutzername oder diese E-Mail-Adresse ist bereits vergeben.")
        rotate_session(request, uid)
        return redirect("/studio")

@app.post("/login")
async def login(request: Request):
    async with request.form(max_files=0, max_fields=10) as form:
        csrf_check(request, form)
        rate(request, "login_ip", 30)
        name = field(form, "username", 1, 254).lower()
        rate(request, "login_account", 10, identity=name)
        password = str(form.get("password", ""))[:129]
        user = request.state.db.execute("SELECT * FROM users WHERE username=? OR email=?", (name, name)).fetchone()
        try:
            await run_in_threadpool(ph.verify, user["password_hash"] if user else DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(400, "Anmeldedaten sind nicht korrekt.")
        if not user:
            raise HTTPException(400, "Anmeldedaten sind nicht korrekt.")
        if ph.check_needs_rehash(user["password_hash"]):
            hashed = await run_in_threadpool(ph.hash, password)
            with request.state.db:
                request.state.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user["id"]))
        admin_check_login_allowed(request, user["id"])
        rotate_session(request, user["id"])
        return redirect("/")

@app.post("/logout")
async def logout(request: Request):
    async with request.form(max_files=0, max_fields=2) as form:
        csrf_check(request, form)
        rotate_session(request)
        return redirect("/")

@app.get("/channel/{username}")
def channel(request: Request, username: str, page: int = 1):
    db = request.state.db
    creator = db.execute(
        "SELECT u.*,(SELECT COUNT(*) FROM subscriptions WHERE creator_id=u.id) AS subscribers,"
        "(SELECT COALESCE(SUM(views),0) FROM videos WHERE user_id=u.id) AS views "
        "FROM users u WHERE username=?", (username,)).fetchone()
    if not creator:
        raise HTTPException(404, "Diesen Kanal gibt es nicht.")
    page = max(1, min(page, 10000))
    videos, more = get_videos(db, "WHERE v.user_id=?", (creator["id"],), page=page)
    subscribed = bool(request.state.user and db.execute(
        "SELECT 1 FROM subscriptions WHERE subscriber_id=? AND creator_id=?",
        (request.state.user["id"], creator["id"])).fetchone())
    return render(request, "channel.html", creator=creator, videos=videos, subscribed=subscribed,
                  page=page, more=more, paging=f"/channel/{quote(username)}?page=")

@app.post("/channel/{username}/subscribe")
async def subscribe(request: Request, username: str):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=3) as form:
        csrf_check(request, form)
        rate(request, "subscribe", 60, identity=str(user["id"]))
        db = request.state.db
        creator = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not creator:
            raise HTTPException(404, "Kanal nicht gefunden.")
        if creator["id"] == user["id"]:
            raise HTTPException(400, "Du kannst deinen eigenen Kanal nicht abonnieren.")
        with db:
            row = db.execute("DELETE FROM subscriptions WHERE subscriber_id=? AND creator_id=?",
                             (user["id"], creator["id"]))
            if not row.rowcount:
                db.execute("INSERT INTO subscriptions VALUES(?,?,?)", (user["id"], creator["id"], now()))
        vid = str(form.get("video_id", ""))
        return redirect(f"/watch/{vid}" if re.fullmatch(r"[a-f0-9]{32}", vid) else f"/channel/{username}")

@app.get("/watch/{vid}")
def watch(request: Request, vid: str):
    db = request.state.db
    video = video_or_404(db, vid)
    uid = request.state.user["id"] if request.state.user else None
    liked = bool(uid and db.execute("SELECT 1 FROM likes WHERE user_id=? AND video_id=?", (uid, vid)).fetchone())
    subscribed = bool(uid and db.execute("SELECT 1 FROM subscriptions WHERE subscriber_id=? AND creator_id=?", (uid, video["user_id"])).fetchone())
    count = db.execute("SELECT COUNT(*) FROM subscriptions WHERE creator_id=?", (video["user_id"],)).fetchone()[0]
    comments = db.execute(
        "SELECT c.*,u.username,u.display_name FROM comments c JOIN users u ON u.id=c.user_id "
        "WHERE video_id=? ORDER BY c.created_at DESC,c.id DESC LIMIT 100", (vid,)).fetchall()
    comment_count = db.execute("SELECT COUNT(*) FROM comments WHERE video_id=?", (vid,)).fetchone()[0]
    recommended = db.execute(VIDEO_QUERY + "WHERE v.id!=? AND " + public_video_clause("v") + " ORDER BY (v.category=?) DESC,v.views DESC LIMIT 6", (vid, video["category"])).fetchall()
    return render(request, "watch.html", video=video, liked=liked, subscribed=subscribed,
                  subscriber_count=count, comments=comments, comment_count=comment_count,
                  recommended=recommended, share_url=f"{PUBLIC_URL}/watch/{vid}")

@app.post("/api/videos/{vid}/view")
def count_view(request: Request, vid: str):
    csrf_check(request)
    rate(request, "views", 120, identity=request.state.session["token_hash"])
    db = request.state.db
    video_or_404(db, vid)
    viewer = token_hash(f"user:{request.state.user['id']}") if request.state.user else request.state.session["token_hash"]
    with db:
        cursor = db.execute("INSERT OR IGNORE INTO view_events VALUES(?,?,?)", (vid, viewer, now() // 86400))
        if cursor.rowcount:
            db.execute("UPDATE videos SET views=views+1 WHERE id=?", (vid,))
    return {"views": db.execute("SELECT views FROM videos WHERE id=?", (vid,)).fetchone()[0]}

@app.post("/watch/{vid}/like")
async def like(request: Request, vid: str):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=2) as form:
        csrf_check(request, form)
        rate(request, "likes", 90, identity=str(user["id"]))
        db = request.state.db
        video_or_404(db, vid)
        with db:
            row = db.execute("DELETE FROM likes WHERE user_id=? AND video_id=?", (user["id"], vid))
            if not row.rowcount:
                db.execute("INSERT INTO likes VALUES(?,?)", (user["id"], vid))
    return redirect(f"/watch/{vid}")

@app.post("/watch/{vid}/comment")
async def comment(request: Request, vid: str):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=3) as form:
        csrf_check(request, form)
        rate(request, "comments", 12, 600, identity=str(user["id"]))
        body = field(form, "body", 1, 2000)
        db = request.state.db
        video_or_404(db, vid)
        with db:
            db.execute("INSERT INTO comments(user_id,video_id,body,created_at) VALUES(?,?,?,?)",
                       (user["id"], vid, body, now()))
    return redirect(f"/watch/{vid}#comments")

@app.post("/comments/{cid}/delete")
async def delete_comment(request: Request, cid: int):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=2) as form:
        csrf_check(request, form)
        db = request.state.db
        item = db.execute("SELECT c.*,v.user_id AS owner_id FROM comments c JOIN videos v ON v.id=c.video_id WHERE c.id=?", (cid,)).fetchone()
        if not item:
            raise HTTPException(404, "Kommentar nicht gefunden.")
        if user["id"] not in (item["user_id"], item["owner_id"]):
            raise HTTPException(403, "Du darfst diesen Kommentar nicht löschen.")
        with db:
            db.execute("DELETE FROM comments WHERE id=?", (cid,))
    return redirect(f"/watch/{item['video_id']}#comments")

@app.get("/upload")
def upload_page(request: Request):
    require_user(request)
    return render(request, "upload.html", max_mb=MAX_VIDEO_BYTES // 1024**2)

def process_video(source, suffix, target, poster):
    """Parse locally, never accept remote URLs or filenames from upload metadata."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
             "-show_entries", "format=duration,format_name:stream=codec_type,codec_name,width,height",
             "-of", "json", str(source)], capture_output=True, timeout=30, check=True)
        info = json.loads(result.stdout)
        fmt = info.get("format", {})
        streams = info.get("streams", [])
        visual = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        length = float(fmt.get("duration", 0))
        allowed_format = ("mov" in fmt.get("format_name", "")) if suffix == ".mp4" else ("webm" in fmt.get("format_name", ""))
        allowed_codec = ["h264"] if suffix == ".mp4" else ["vp8", "vp9", "av1"]
        if (not visual or not allowed_format or visual.get("codec_name") not in allowed_codec
            or not math.isfinite(length) or not 0.2 <= length <= 4 * 3600
            or max(visual.get("width", 0), visual.get("height", 0)) > 4096
            or any(s.get("codec_name") not in ("aac", "mp3", "opus", "vorbis") for s in audio)):
            raise ValueError("Unsupported media")
        # Remux into a fresh container, strip metadata/attachments. No CPU-heavy transcode.
        command = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                   "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                   "-map_metadata", "-1", "-map_chapters", "-1"]
        if suffix == ".mp4":
            command += ["-movflags", "+faststart"]
        subprocess.run(command + ["-y", str(target)], check=True, capture_output=True, timeout=120)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
             "-ss", str(min(1, length / 3)), "-i", str(target), "-frames:v", "1",
             "-vf", "scale=960:-2", "-y", str(poster)], check=True, capture_output=True, timeout=45)
        return length
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError, OSError):
        raise HTTPException(400, "Video nicht unterstützt. Nutze MP4 mit H.264/AAC oder WebM mit VP8/VP9/AV1 und Opus/Vorbis. Maximal 4 Stunden und 4096 Pixel.")

@app.post("/upload")
async def upload(request: Request):
    user = require_user(request)
    rate(request, "upload", 10, 3600, identity=str(user["id"]))
    async with request.form(max_files=1, max_fields=8) as form:
        csrf_check(request, form)
        title = field(form, "title", 3, 140)
        description = field(form, "description", 0, 5000)
        category = field(form, "category", 1, 40)
        if category not in CATEGORIES:
            raise HTTPException(400, "Bitte wähle eine gültige Kategorie.")
        file = form.get("video")
        if not file or not hasattr(file, "read"):
            raise HTTPException(400, "Bitte wähle eine Videodatei aus.")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in (".mp4", ".webm"):
            raise HTTPException(400, "Nur MP4 und WebM sind erlaubt.")
        vid = uuid.uuid4().hex
        source, target, poster = MEDIA / f"{vid}.part", MEDIA / f"{vid}{suffix}", MEDIA / f"{vid}.jpg"
        size, committed = 0, False
        try:
            with source.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise HTTPException(413, "Das Video ist zu gross.")
                    output.write(chunk)
            if size < 64:
                raise HTTPException(400, "Die Videodatei ist leer oder beschädigt.")
            db = request.state.db
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM videos WHERE user_id=?", (user["id"],)).fetchone()[0]
            if used + size > MAX_USER_BYTES:
                raise HTTPException(413, "Dein Speicherlimit wurde erreicht. Lösche zuerst alte Videos.")
            length = await run_in_threadpool(process_video, source, suffix, target, poster)
            actual_size = target.stat().st_size
            # Serialize quota check + insert to prevent concurrent uploads bypassing quota.
            with db:
                db.execute("BEGIN IMMEDIATE")
                used = db.execute("SELECT COALESCE(SUM(size),0) FROM videos WHERE user_id=?", (user["id"],)).fetchone()[0]
                if used + actual_size > MAX_USER_BYTES:
                    raise HTTPException(413, "Dein Speicherlimit wurde erreicht.")
                db.execute(
                    "INSERT INTO videos(id,user_id,title,description,category,filename,poster,duration,size,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (vid, user["id"], title, description, category, target.name, poster.name, length, actual_size, now()))
            committed = True
        finally:
            source.unlink(missing_ok=True)
            if not committed:
                target.unlink(missing_ok=True)
                poster.unlink(missing_ok=True)
    return redirect(f"/watch/{vid}")

@app.get("/media/{vid}")
def media(request: Request, vid: str):
    video = video_or_404(request.state.db, vid)
    path = MEDIA / video["filename"]
    if not path.is_file():
        raise HTTPException(404, "Die Videodatei fehlt.")
    return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else "video/webm",
                        headers={"Content-Disposition": "inline"})

@app.get("/poster/{vid}")
def poster(request: Request, vid: str):
    video = video_or_404(request.state.db, vid)
    if not video["poster"] or not (MEDIA / video["poster"]).is_file():
        raise HTTPException(404, "Vorschaubild nicht gefunden.")
    return FileResponse(MEDIA / video["poster"], media_type="image/jpeg")

@app.get("/studio")
def studio(request: Request):
    user = require_user(request)
    db = request.state.db
    stats = db.execute(
        "SELECT COUNT(*) AS videos,COALESCE(SUM(views),0) AS views,COALESCE(SUM(size),0) AS bytes FROM videos WHERE user_id=?", (user["id"],)).fetchone()
    likes = db.execute("SELECT COUNT(*) FROM likes l JOIN videos v ON v.id=l.video_id WHERE v.user_id=?", (user["id"],)).fetchone()[0]
    subscribers = db.execute("SELECT COUNT(*) FROM subscriptions WHERE creator_id=?", (user["id"],)).fetchone()[0]
    videos = db.execute(VIDEO_QUERY + "WHERE v.user_id=? ORDER BY v.created_at DESC", (user["id"],)).fetchall()
    return render(request, "studio.html", stats=stats, likes=likes, subscribers=subscribers, videos=videos,
                  used_mb=round(stats["bytes"] / 1024**2, 1), quota_mb=MAX_USER_BYTES // 1024**2)

@app.get("/settings")
def settings(request: Request):
    require_user(request)
    return render(request, "settings.html")

@app.post("/settings")
async def update_settings(request: Request):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=5) as form:
        csrf_check(request, form)
        name = field(form, "display_name", 2, 60)
        bio = field(form, "bio", 0, 1500)
        with request.state.db:
            request.state.db.execute("UPDATE users SET display_name=?,bio=? WHERE id=?", (name, bio, user["id"]))
    return redirect(f"/channel/{user['username']}")

@app.post("/settings/password")
async def update_password(request: Request):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=5) as form:
        csrf_check(request, form)
        rate(request, "password", 5, identity=str(user["id"]))
        old, new = str(form.get("old_password", "")), str(form.get("password", ""))
        if not 12 <= len(new) <= 128:
            raise HTTPException(400, "Das neue Passwort muss 12–128 Zeichen enthalten.")
        try:
            await run_in_threadpool(ph.verify, user["password_hash"], old[:129])
        except (VerificationError, InvalidHashError):
            raise HTTPException(400, "Das bisherige Passwort ist nicht korrekt.")
        hashed = await run_in_threadpool(ph.hash, new)
        with request.state.db:
            request.state.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user["id"]))
            request.state.db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        rotate_session(request, user["id"])
    return redirect("/settings?saved=1")

@app.get("/studio/{vid}/edit")
def edit_video_page(request: Request, vid: str):
    user = require_user(request)
    video = video_or_404(request.state.db, vid)
    if video["user_id"] != user["id"]:
        raise HTTPException(403, "Dieses Video gehört nicht dir.")
    return render(request, "edit.html", video=video)

@app.post("/studio/{vid}/edit")
async def edit_video(request: Request, vid: str):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=5) as form:
        csrf_check(request, form)
        db = request.state.db
        video = video_or_404(db, vid)
        if video["user_id"] != user["id"]:
            raise HTTPException(403, "Dieses Video gehört nicht dir.")
        title, description = field(form, "title", 3, 140), field(form, "description", 0, 5000)
        category = field(form, "category", 1, 40)
        if category not in CATEGORIES:
            raise HTTPException(400, "Ungültige Kategorie.")
        with db:
            db.execute("UPDATE videos SET title=?,description=?,category=? WHERE id=?", (title, description, category, vid))
    return redirect("/studio")

@app.post("/studio/{vid}/delete")
async def delete_video(request: Request, vid: str):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=2) as form:
        csrf_check(request, form)
        db = request.state.db
        video = video_or_404(db, vid)
        if video["user_id"] != user["id"]:
            raise HTTPException(403, "Dieses Video gehört nicht dir.")
        with db:
            db.execute("DELETE FROM videos WHERE id=?", (vid,))
        (MEDIA / video["filename"]).unlink(missing_ok=True)
        if video["poster"]:
            (MEDIA / video["poster"]).unlink(missing_ok=True)
    return redirect("/studio")


@app.post("/settings/delete-account")
async def delete_account(request: Request):
    user = require_user(request)
    async with request.form(max_files=0, max_fields=4) as form:
        csrf_check(request, form)
        rate(request, "delete_account", 5, identity=str(user["id"]))
        password = str(form.get("password", ""))[:129]
        try:
            await run_in_threadpool(ph.verify, user["password_hash"], password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(400, "Das Passwort ist nicht korrekt.")
        db = request.state.db
        files = db.execute("SELECT filename,poster FROM videos WHERE user_id=?", (user["id"],)).fetchall()
        with db:
            db.execute("DELETE FROM users WHERE id=?", (user["id"],))
        for item in files:
            (MEDIA / item["filename"]).unlink(missing_ok=True)
            if item["poster"]:
                (MEDIA / item["poster"]).unlink(missing_ok=True)
        rotate_session(request)
    return redirect("/")


# STREAMLY_LIVE_UPDATE_V1
from .streamly_extension import router as streamly_extension_router
app.include_router(streamly_extension_router)


# STREAMLY_ADMIN_UPDATE_V1
from .streamly_admin import (router as streamly_admin_router, public_video_clause, public_creator_clause,
    assert_user_active as admin_assert_user_active, check_login_allowed as admin_check_login_allowed,
    register_media_guard as register_streamly_admin_guard)
app.include_router(streamly_admin_router)
register_streamly_admin_guard(app)


# STREAMLY_SECURITY_UPDATE_V1
from .streamly_security import router as streamly_security_router
app.include_router(streamly_security_router)
