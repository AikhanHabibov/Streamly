'''Isolated adapter tests. The user's original project is not available here.'''
import hashlib
import importlib.util
import json
import secrets
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

PACKAGE = Path(__file__).resolve().parents[1]

@pytest.fixture
def platform(tmp_path, monkeypatch):
    core = types.ModuleType("app.main")
    app_package = types.ModuleType("app")
    app_package.__path__ = [str(PACKAGE / "payload/app")]
    app_package.main = core
    monkeypatch.setitem(sys.modules, "app", app_package)
    monkeypatch.setitem(sys.modules, "app.main", core)
    monkeypatch.setenv("STREAMLY_INTERNAL_SECRET", "a" * 64)
    core.DATA = tmp_path
    core.MEDIA = tmp_path / "media"
    core.MEDIA.mkdir()
    core.MAX_VIDEO_BYTES = 2 * 1024**3
    core.MAX_USER_BYTES = 20 * 1024**3
    core.CATEGORIES = ["Gaming", "Technologie", "Musik", "Kreativ", "Wissen", "Lifestyle"]
    core.now = lambda: int(time.time())
    db_path = tmp_path / "test.sqlite3"
    def connect():
        db = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db
    core.connect = connect
    db = connect()
    db.executescript('''
        CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,display_name TEXT);
        INSERT INTO users VALUES(1,'alice','Alice'),(2,'bob','Bob');
        CREATE TABLE videos(id TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        title TEXT,description TEXT,category TEXT,filename TEXT,poster TEXT,duration REAL,size INTEGER,created_at INTEGER);
    ''')
    db.executescript((PACKAGE / "payload/app/streamly_schema.sql").read_text())
    db.commit(); db.close()
    def require_user(request):
        if not request.state.user:
            raise HTTPException(401, "Bitte anmelden.")
        return request.state.user
    core.require_user = require_user
    def csrf_check(request, form=None):
        token = str(form.get("csrf", "")) if form is not None else request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(token.encode(), b"test-csrf"):
            raise HTTPException(403, "CSRF fehlgeschlagen.")
    core.csrf_check = csrf_check
    def field(form, name, low, high):
        value = str(form.get(name, "")).strip()
        if not low <= len(value) <= high:
            raise HTTPException(400, "Ungueltiges Feld")
        return value
    core.field = field
    core.rate = lambda *a, **kw: None  # Existing core rate limits are not re-tested here.
    core.redirect = lambda path: RedirectResponse(path, status_code=303)
    core.HTMLResponse = HTMLResponse
    def process_video(source, suffix, target, poster):
        try:
            info = json.loads(subprocess.check_output(
                ["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,codec_name",
                 "-of","json",str(source)], stderr=subprocess.PIPE))
            duration = float(info["format"]["duration"])
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            if suffix != ".mp4" or video["codec_name"] != "h264":
                raise ValueError()
            subprocess.run(["ffmpeg","-v","error","-i",str(source),"-map","0:v:0","-map","0:a:0?",
                            "-c","copy","-movflags","+faststart","-y",str(target)],check=True,capture_output=True)
            subprocess.run(["ffmpeg","-v","error","-i",str(target),"-frames:v","1",
                            "-vf","scale=320:-2","-y",str(poster)],check=True,capture_output=True)
            return duration
        except Exception:
            raise HTTPException(400, "Kein unterstuetztes Video.")
    core.process_video = process_video
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    for p in (PACKAGE / "payload/app/templates").glob("*.html"):
        (template_dir / p.name).write_bytes(p.read_bytes())
    (template_dir / "base.html").write_text(
        '<html><head><title>{% block title %}{% endblock %}</title></head><body>{% block content %}{% endblock %}</body></html>')
    (template_dir / "components.html").write_text(
        '{% macro icon(name,size=20) %}<svg></svg>{% endmacro %}'
        '{% macro csrf_field(csrf) %}<input name="csrf" value="{{csrf}}">{% endmacro %}')
    templates = Jinja2Templates(directory=str(template_dir))
    def render(request, template, **kwargs):
        return templates.TemplateResponse(request=request, name=template, context={
            "user": request.state.user, "csrf": "test-csrf", "categories": core.CATEGORIES, **kwargs})
    core.render = render

    name = "app.streamly_extension"
    spec = importlib.util.spec_from_file_location(name, PACKAGE / "payload/app/streamly_extension.py")
    ext = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, ext)
    spec.loader.exec_module(ext)
    monkeypatch.setattr(ext, "media_api", lambda path="/v3/paths/list", method="GET": {"items":[]})
    app = FastAPI()
    @app.middleware("http")
    async def state(request: Request, call_next):
        db = connect()
        request.state.db = db
        user = request.headers.get("x-test-user", "1")
        request.state.user = db.execute("SELECT * FROM users WHERE id=?", (user,)).fetchone() if user else None
        try:
            return await call_next(request)
        finally:
            db.close()
    app.include_router(ext.router)
    with TestClient(app) as client:
        yield client, core, ext

@pytest.fixture
def original_project(tmp_path):
    '''Minimal known source anchors for installer validation, not the original app.'''
    project = tmp_path / "original"
    (project / "app/templates").mkdir(parents=True)
    (project / "app/main.py").write_text('''
from urllib.parse import urlsplit
PRODUCTION = False
PUBLIC_URL = "http://127.0.0.1:8000"
def require_user(request): pass
def csrf_check(request, form=None): pass
def process_video(source, suffix, target, poster): pass
def connect(): pass
def field(form,name,low,high): pass
class BodyLimit:
    def dummy(self,scope):
        limit = MAX_VIDEO_BYTES + 2 * 1024 * 1024 if scope["path"] == "/upload" else 128 * 1024
allowed_hosts=[urlsplit(PUBLIC_URL).hostname] if PRODUCTION else ["localhost", "127.0.0.1", "testserver"],
def fake_middleware(request,response):
    needs_session = not request.url.path.startswith(("/media/", "/poster/", "/health"))
    response.headers["Cache-Control"] = "no-store" if needs_session else "private, max-age=300"
''')
    (project / "app/schema.sql").write_text("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY);")
    (project / "app/templates/base.html").write_text('''
<html><head><title>StreamNest</title></head><body>
stream<span>nest</span>
<nav class="side-nav" aria-label="Hauptnavigation"></nav>
</body></html>
''')
    (project / "app/templates/studio.html").write_text('{% block content %}<h1>Studio</h1>{% endblock %}')
    (project / ".env").write_text("DOMAIN=existing.example\n")
    return project
