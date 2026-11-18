"""Add-on for the supplied StreamNest/Streamly FastAPI project.
No replacement for production media infrastructure or a security audit.
"""
import base64
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from . import main as core

router = APIRouter()
log = logging.getLogger("streamly.extension")
CHUNK_SIZE = 8 * 1024 * 1024
TTL = 24 * 3600
UPLOAD_DIR = core.DATA / "upload_chunks"
SECRET = os.getenv("STREAMLY_INTERNAL_SECRET", "")
API_URL = os.getenv("STREAMLY_MEDIA_API", "http://mediamtx:9997").rstrip("/")
HLS_URL = os.getenv("STREAMLY_MEDIA_HLS", "http://mediamtx:8888").rstrip("/")
RTMP_URL = os.getenv("STREAMLY_RTMP_URL", "rtmp://127.0.0.1:1935").rstrip("/")
ID = re.compile(r"^[a-f0-9]{32}$")
STREAM_PATH = re.compile(r"^live_[a-f0-9]{32}$")

def ensure_id(value):
    if not ID.fullmatch(value):
        raise HTTPException(404, "Upload nicht gefunden.")

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def cleanup_uploads(db):
    """Only expired work directories; never delete completed media files."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    expired = db.execute(
        "SELECT id FROM streamly_uploads WHERE updated_at<?", (core.now() - TTL,)).fetchall()
    for row in expired:
        if ID.fullmatch(row["id"]):
            shutil.rmtree(UPLOAD_DIR / row["id"], ignore_errors=True)
    with db:
        db.execute("DELETE FROM streamly_uploads WHERE updated_at<?", (core.now() - TTL,))
    # Remove old orphan directories too (e.g. account deletion / failed initialization).
    for child in UPLOAD_DIR.iterdir():
        if child.is_dir() and ID.fullmatch(child.name) and child.stat().st_mtime < core.now() - TTL:
            if not db.execute("SELECT 1 FROM streamly_uploads WHERE id=?", (child.name,)).fetchone():
                shutil.rmtree(child, ignore_errors=True)

def own_upload(request, upload_id):
    user = core.require_user(request)
    ensure_id(upload_id)
    row = request.state.db.execute(
        "SELECT * FROM streamly_uploads WHERE id=? AND user_id=?",
        (upload_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Upload nicht gefunden oder abgelaufen.")
    if row["updated_at"] < core.now() - TTL:
        with request.state.db:
            request.state.db.execute("DELETE FROM streamly_uploads WHERE id=?", (upload_id,))
        shutil.rmtree(UPLOAD_DIR / upload_id, ignore_errors=True)
        raise HTTPException(404, "Dieser Upload ist abgelaufen. Bitte beginne erneut.")
    return row

def stored_chunks(row):
    directory = UPLOAD_DIR / row["id"]
    count = math.ceil(row["expected_size"] / CHUNK_SIZE)
    return [i for i in range(count) if (directory / f"{i:06}.chunk").is_file()]

def upload_status(row):
    return {"id": row["id"], "state": row["state"], "video_id": row["video_id"],
            "error": row["error"], "received": stored_chunks(row) if row["state"] == "open" else [],
            "chunk_size": CHUNK_SIZE, "size": row["expected_size"]}

@router.post("/api/uploads/init")
async def start_upload(request: Request):
    user = core.require_user(request)
    core.csrf_check(request)
    core.rate(request, "chunk_init", 10, 3600, identity=str(user["id"]))
    try:
        metadata = await request.json()
        if not isinstance(metadata, dict):
            raise ValueError
        size = metadata.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(400, "Ungültige Upload-Daten.")
    if not 64 <= size <= core.MAX_VIDEO_BYTES:
        raise HTTPException(413, "Diese Datei überschreitet das Videolimit oder ist leer.")
    title = core.field(metadata, "title", 3, 140)
    description = core.field(metadata, "description", 0, 5000)
    category = core.field(metadata, "category", 1, 40)
    suffix = Path(str(metadata.get("filename", ""))[:255]).suffix.lower()
    if category not in core.CATEGORIES or suffix not in (".mp4", ".webm"):
        raise HTTPException(400, "Bitte wähle eine gültige Kategorie und eine MP4-/WebM-Datei.")
    db = request.state.db
    await run_in_threadpool(cleanup_uploads, db)
    uid = uuid.uuid4().hex
    if shutil.disk_usage(core.DATA).free < size * 3 + 512 * 1024 * 1024:
        raise HTTPException(507, "Zu wenig freier Serverspeicher. Für Upload und Verarbeitung wird zeitweise etwa die dreifache Dateigrösse benötigt.")
    with db:
        db.execute("BEGIN IMMEDIATE")
        pending = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(expected_size),0) FROM streamly_uploads "
            "WHERE user_id=? AND state IN ('open','processing')", (user["id"],)).fetchone()
        used = db.execute("SELECT COALESCE(SUM(size),0) FROM videos WHERE user_id=?", (user["id"],)).fetchone()[0]
        if pending[0] >= 3:
            raise HTTPException(409, "Du hast schon drei offene Uploads. Setze einen fort oder brich ihn ab.")
        if used + pending[1] + size > core.MAX_USER_BYTES:
            raise HTTPException(413, "Dein Kontospeicher reicht für dieses Video nicht aus.")
        db.execute(
            "INSERT INTO streamly_uploads(id,user_id,metadata,expected_size,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (uid, user["id"], json.dumps({"title": title, "description": description,
             "category": category, "suffix": suffix}), size, core.now(), core.now()))
    try:
        (UPLOAD_DIR / uid).mkdir()
    except OSError:
        with db:
            db.execute("DELETE FROM streamly_uploads WHERE id=?", (uid,))
        raise HTTPException(507, "Es ist kein temporärer Speicher verfügbar.")
    return {"id": uid, "chunk_size": CHUNK_SIZE}


@router.patch("/api/uploads/{upload_id}/metadata")
async def update_upload_metadata(request: Request, upload_id: str):
    row = own_upload(request, upload_id)
    core.csrf_check(request)
    if row["state"] != "open":
        raise HTTPException(409, "Die Metadaten können jetzt nicht mehr geändert werden.")
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Ungültige Metadaten.")
    metadata = json.loads(row["metadata"])
    metadata.update(title=core.field(payload, "title", 3, 140),
                    description=core.field(payload, "description", 0, 5000),
                    category=core.field(payload, "category", 1, 40))
    if metadata["category"] not in core.CATEGORIES:
        raise HTTPException(400, "Ungültige Kategorie.")
    with request.state.db:
        request.state.db.execute(
            "UPDATE streamly_uploads SET metadata=?,updated_at=? WHERE id=? AND state='open'",
            (json.dumps(metadata), core.now(), upload_id))
    return {"updated": True}

@router.get("/api/uploads/{upload_id}/status")
def get_upload_status(request: Request, upload_id: str):
    row = own_upload(request, upload_id)
    if row["state"] == "processing" and row["updated_at"] < core.now() - 1800:
        with request.state.db:
            request.state.db.execute(
                "UPDATE streamly_uploads SET state='failed',error=? WHERE id=? AND state='processing'",
                ("Die Verarbeitung wurde unterbrochen. Bitte starte den Upload erneut.", upload_id))
        row = own_upload(request, upload_id)
    return upload_status(row)

@router.put("/api/uploads/{upload_id}/chunks/{index}")
async def put_chunk(request: Request, upload_id: str, index: int):
    row = own_upload(request, upload_id)
    core.csrf_check(request)
    if row["state"] != "open":
        raise HTTPException(409, "Dieser Upload nimmt keine weiteren Teile an.")
    count = math.ceil(row["expected_size"] / CHUNK_SIZE)
    if not 0 <= index < count:
        raise HTTPException(400, "Ungültige Teilnummer.")
    expected = min(CHUNK_SIZE, row["expected_size"] - index * CHUNK_SIZE)
    directory = UPLOAD_DIR / upload_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{index:06}.chunk"
    if target.is_file():
        return {"index": index, "stored": True}
    # Immutable chunk targets: concurrent retries must never replace committed bytes.
    temporary = directory / f"{index:06}.{uuid.uuid4().hex}.tmp"
    size = 0
    try:
        with temporary.open("xb") as output:
            async for block in request.stream():
                size += len(block)
                if size > expected:
                    raise HTTPException(413, "Dieser Teil ist zu gross.")
                output.write(block)
        if size != expected:
            raise HTTPException(400, "Dieser Teil ist unvollständig. Bitte erneut übertragen.")
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        with request.state.db:
            request.state.db.execute("UPDATE streamly_uploads SET updated_at=? WHERE id=?",
                                     (core.now(), upload_id))
    except OSError:
        raise HTTPException(507, "Der Videoteil konnte nicht gespeichert werden.")
    finally:
        temporary.unlink(missing_ok=True)
    return {"index": index, "stored": True}

@router.delete("/api/uploads/{upload_id}")
def cancel_upload(request: Request, upload_id: str):
    row = own_upload(request, upload_id)
    core.csrf_check(request)
    if row["state"] == "processing":
        raise HTTPException(409, "Die Videoverarbeitung läuft bereits.")
    with request.state.db:
        request.state.db.execute("DELETE FROM streamly_uploads WHERE id=?", (upload_id,))
    shutil.rmtree(UPLOAD_DIR / upload_id, ignore_errors=True)
    return {"cancelled": True}

def finish_upload(upload_id):
    """Background task: survives a closed browser, not a crashed application worker."""
    db = core.connect()
    directory = UPLOAD_DIR / upload_id
    source = directory / "assembled.part"
    target = poster = None
    committed = False
    try:
        row = db.execute("SELECT * FROM streamly_uploads WHERE id=? AND state='processing'", (upload_id,)).fetchone()
        if not row:
            return
        metadata = json.loads(row["metadata"])
        count = math.ceil(row["expected_size"] / CHUNK_SIZE)
        with source.open("wb") as output:
            for index in range(count):
                path = directory / f"{index:06}.chunk"
                expected = min(CHUNK_SIZE, row["expected_size"] - index * CHUNK_SIZE)
                if not path.is_file() or path.stat().st_size != expected:
                    raise HTTPException(400, "Ein Videoteil fehlt. Bitte starte den Upload erneut.")
                with path.open("rb") as part:
                    shutil.copyfileobj(part, output, length=1024 * 1024)
        if source.stat().st_size != row["expected_size"]:
            raise HTTPException(400, "Die zusammengesetzte Datei ist unvollständig.")
        vid = uuid.uuid4().hex
        target, poster = core.MEDIA / f"{vid}{metadata['suffix']}", core.MEDIA / f"{vid}.jpg"
        duration = core.process_video(source, metadata["suffix"], target, poster)
        size = target.stat().st_size
        with db:
            db.execute("BEGIN IMMEDIATE")
            # User may have deleted their account while processing.
            if not db.execute("SELECT 1 FROM users WHERE id=?", (row["user_id"],)).fetchone():
                raise HTTPException(400, "Das Konto existiert nicht mehr.")
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM videos WHERE user_id=?", (row["user_id"],)).fetchone()[0]
            reserved = db.execute(
                "SELECT COALESCE(SUM(expected_size),0) FROM streamly_uploads "
                "WHERE user_id=? AND id!=? AND state IN ('open','processing')",
                (row["user_id"], upload_id)).fetchone()[0]
            if used + reserved + size > core.MAX_USER_BYTES:
                raise HTTPException(413, "Dein Kontospeicher reicht nicht aus.")
            db.execute(
                "INSERT INTO videos(id,user_id,title,description,category,filename,poster,duration,size,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (vid, row["user_id"], metadata["title"], metadata["description"], metadata["category"],
                 target.name, poster.name, duration, size, core.now()))
            db.execute("UPDATE streamly_uploads SET state='done',video_id=?,updated_at=? WHERE id=?",
                       (vid, core.now(), upload_id))
        committed = True
    except Exception as exc:
        message = str(exc.detail) if isinstance(exc, HTTPException) else "Verarbeitung fehlgeschlagen. Bitte prüfe die Serverlogs und lade erneut hoch."
        log.warning("Upload processing failed for %s: %s", upload_id, type(exc).__name__)
        with db:
            db.execute("UPDATE streamly_uploads SET state='failed',error=?,updated_at=? WHERE id=?",
                       (message, core.now(), upload_id))
    finally:
        if not committed:
            if target:
                target.unlink(missing_ok=True)
            if poster:
                poster.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)
        db.close()

@router.post("/api/uploads/{upload_id}/finish")
def finalize_upload(request: Request, upload_id: str, tasks: BackgroundTasks):
    row = own_upload(request, upload_id)
    core.csrf_check(request)
    if row["state"] in ("done", "failed"):
        return upload_status(row)
    db = request.state.db
    if row["state"] == "processing":
        if row["updated_at"] > core.now() - 1800:
            return JSONResponse({"state": "processing"}, status_code=202)
        # Interrupted tasks are not resumed automatically: fail visibly, never duplicate.
        with db:
            db.execute("UPDATE streamly_uploads SET state='failed',error=? WHERE id=?",
                       ("Die Verarbeitung wurde unterbrochen. Bitte starte den Upload erneut.", upload_id))
        raise HTTPException(409, "Die Verarbeitung wurde unterbrochen. Bitte starte den Upload erneut.")
    expected = math.ceil(row["expected_size"] / CHUNK_SIZE)
    if len(stored_chunks(row)) != expected:
        raise HTTPException(409, "Es fehlen noch Teile dieses Videos.")
    with db:
        changed = db.execute(
            "UPDATE streamly_uploads SET state='processing',updated_at=? WHERE id=? AND state='open'",
            (core.now(), upload_id)).rowcount
    if changed:
        tasks.add_task(finish_upload, upload_id)
    return JSONResponse({"state": "processing"}, status_code=202)

def media_api(path="/v3/paths/list", method="GET"):
    request = urllib.request.Request(API_URL + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read(1024 * 1024)
            return json.loads(body) if body else {}
    except (OSError, ValueError):
        return None

def live_state():
    """Read real ready paths. Do not fabricate live badges or viewer counts."""
    result = media_api("/v3/paths/list?itemsPerPage=200")
    if result is None:
        return None
    return {item["name"]: item for item in result.get("items", []) if item.get("online", item.get("ready", False))}

def live_channel(db, username):
    return db.execute(
        "SELECT s.*,u.username,u.display_name FROM streamly_live_channels s "
        "JOIN users u ON u.id=s.user_id WHERE u.username=?", (username,)).fetchone()

def kick_path(path):
    state = live_state()
    item = (state or {}).get(path)
    source = item.get("source") if item else None
    if source and source.get("type") == "rtmpConn" and re.fullmatch(r"[a-f0-9-]{36}", source.get("id", "")):
        media_api("/v3/rtmp/conns/kick/" + source["id"], method="POST")

def studio_page(request, channel, stream_key=""):
    status = live_state()
    online = bool(channel and status and channel["path"] in status)
    return core.render(request, "streamly_live_studio.html", live_channel=channel,
                       stream_key=stream_key, rtmp_url=RTMP_URL, online=online,
                       media_available=status is not None)

@router.get("/studio/live")
def live_studio(request: Request):
    user = core.require_user(request)
    return studio_page(request, live_channel(request.state.db, user["username"]))

@router.post("/studio/live/settings")
async def live_settings(request: Request):
    user = core.require_user(request)
    async with request.form(max_files=0, max_fields=6) as form:
        core.csrf_check(request, form)
        title = core.field(form, "title", 3, 140)
        description = core.field(form, "description", 0, 5000)
        category = core.field(form, "category", 1, 40)
        if category not in core.CATEGORIES:
            raise HTTPException(400, "Ungültige Kategorie.")
        db = request.state.db
        with db:
            db.execute(
                "INSERT INTO streamly_live_channels(user_id,path,title,description,category) VALUES(?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET title=excluded.title,description=excluded.description,category=excluded.category",
                (user["id"], "live_" + uuid.uuid4().hex, title, description, category))
    return core.redirect("/studio/live")

@router.post("/studio/live/key")
async def new_stream_key(request: Request):
    user = core.require_user(request)
    async with request.form(max_files=0, max_fields=2) as form:
        core.csrf_check(request, form)
        core.rate(request, "stream_key", 10, 3600, identity=str(user["id"]))
        if len(SECRET) < 32:
            raise HTTPException(503, "Streaming ist noch nicht konfiguriert. Bitte starte mit compose.live.yaml.")
        db = request.state.db
        old = live_channel(db, user["username"])
        token = secrets.token_hex(32)
        path = "live_" + uuid.uuid4().hex
        with db:
            db.execute(
                "INSERT INTO streamly_live_channels(user_id,path,key_hash,title) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET path=excluded.path,key_hash=excluded.key_hash,enabled=1",
                (user["id"], path, digest(token), "Live mit " + user["display_name"]))
        if old:
            await run_in_threadpool(kick_path, old["path"])
        channel = live_channel(db, user["username"])
        # Deliberately shown only in the response to this POST; never stored as plaintext.
        key = f"{channel['path']}?user={user['username']}&pass={token}"
        return studio_page(request, channel, stream_key=key)

@router.post("/studio/live/disable")
async def disable_stream(request: Request):
    user = core.require_user(request)
    async with request.form(max_files=0, max_fields=2) as form:
        core.csrf_check(request, form)
        channel = live_channel(request.state.db, user["username"])
        if channel:
            with request.state.db:
                request.state.db.execute(
                    "UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE user_id=?", (user["id"],))
            await run_in_threadpool(kick_path, channel["path"])
    return core.redirect("/studio/live")

@router.post("/internal/live-auth")
async def media_auth(request: Request):
    supplied = request.headers.get("authorization", "")
    expected = "Basic " + base64.b64encode(("streamly:" + SECRET).encode()).decode()
    if len(SECRET) < 32 or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(403, "Nicht erlaubt.")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Ungültige Daten.")
    path = str(body.get("path", ""))
    if not STREAM_PATH.fullmatch(path):
        raise HTTPException(403, "Ungültiger Stream.")
    channel = request.state.db.execute(
        "SELECT s.*,u.username FROM streamly_live_channels s JOIN users u ON u.id=s.user_id "
        "WHERE s.path=? AND s.enabled=1", (path,)).fetchone()
    if not channel or not channel["key_hash"]:
        raise HTTPException(403, "Stream deaktiviert.")
    if body.get("action") == "read" and body.get("protocol") == "hls":
        return {"allowed": True}
    if body.get("action") == "publish" and body.get("protocol") == "rtmp":
        password = str(body.get("password", ""))[:256]
        if body.get("user") == channel["username"] and secrets.compare_digest(digest(password), channel["key_hash"]):
            return {"allowed": True}
    raise HTTPException(403, "Falscher Stream-Schlüssel oder nicht erlaubtes Protokoll.")

@router.get("/live")
def browse_live(request: Request):
    state = live_state()
    channels = request.state.db.execute(
        "SELECT s.*,u.username,u.display_name FROM streamly_live_channels s "
        "JOIN users u ON u.id=s.user_id WHERE s.enabled=1 AND s.key_hash!='' ORDER BY u.display_name LIMIT 200").fetchall()
    online = [c for c in channels if state and c["path"] in state]
    return core.render(request, "streamly_live_list.html", live_channels=online,
                       media_available=state is not None)

@router.get("/live/{username}")
def watch_live(request: Request, username: str):
    channel = live_channel(request.state.db, username)
    if not channel or not channel["enabled"] or not channel["key_hash"]:
        raise HTTPException(404, "Dieser Creator hat keinen aktiven Streaming-Kanal.")
    state = live_state()
    online = bool(state and channel["path"] in state)
    return core.render(request, "streamly_live_watch.html", live_channel=channel,
                       online=online, media_available=state is not None)

@router.get("/api/live/{username}/status")
def stream_status(request: Request, username: str):
    channel = live_channel(request.state.db, username)
    if not channel or not channel["enabled"] or not channel["key_hash"]:
        raise HTTPException(404, "Streaming-Kanal nicht verfügbar.")
    state = live_state()
    return JSONResponse({"online": bool(state and channel["path"] in state),
                         "available": state is not None,
                         "playlist": "/hls/" + channel["path"] + "/index.m3u8"}, headers={"Cache-Control": "no-store"})

@router.get("/hls/{path}/{asset}")
def proxy_hls(request: Request, path: str, asset: str):
    if not STREAM_PATH.fullmatch(path) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", asset) or ".." in asset:
        raise HTTPException(404, "Nicht gefunden.")
    if not asset.endswith((".m3u8", ".ts", ".mp4", ".m4s")):
        raise HTTPException(404, "Nicht gefunden.")
    channel = request.state.db.execute(
        "SELECT 1 FROM streamly_live_channels WHERE path=? AND enabled=1 AND key_hash!=''", (path,)).fetchone()
    if not channel:
        raise HTTPException(404, "Stream nicht verfügbar.")
    # Fixed internal upstream and validated segments: never an arbitrary URL proxy.
    try:
        upstream = urllib.request.urlopen(HLS_URL + "/" + path + "/" + asset, timeout=15)
    except urllib.error.HTTPError as exc:
        raise HTTPException(404 if exc.code == 404 else 502, "Der Stream ist noch nicht verfügbar.")
    except OSError:
        raise HTTPException(503, "Der Streaming-Server ist nicht erreichbar.")
    if asset.endswith(".m3u8"):
        try:
            body = upstream.read(256 * 1024 + 1)
        finally:
            upstream.close()
        if len(body) > 256 * 1024:
            raise HTTPException(502, "Ungültige Playlist.")
        return core.HTMLResponse(body, media_type="application/vnd.apple.mpegurl",
                                 headers={"Cache-Control": "no-store"})
    def chunks():
        try:
            while block := upstream.read(256 * 1024):
                yield block
        finally:
            upstream.close()
    media_type = "video/mp2t" if asset.endswith(".ts") else "video/mp4"
    return StreamingResponse(chunks(), media_type=media_type,
                             headers={"Cache-Control": "private, max-age=10"})
