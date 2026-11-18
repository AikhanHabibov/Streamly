import importlib
import importlib.util
import re
import secrets
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PACKAGE=Path(__file__).resolve().parents[1]
LIVE=PACKAGE/"tests/fixture_live"

def installer():
    spec=importlib.util.spec_from_file_location("admin_installer",PACKAGE/"install.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.fixture
def original_project(tmp_path):
    project=tmp_path/"project";app=project/"app"
    shutil.copytree(PACKAGE/"tests/fixture_app",app)
    (app/"__init__.py").write_text("")
    (app/"templates").mkdir()
    # Minimal templates keep source anchors and real server rendering; they are not the user's original UI.
    (app/"templates/base.html").write_text(
        '{% from "components.html" import icon %}<html><head><title>{% block title %}{% endblock %}</title></head><body>'
        '<nav class="side-nav" aria-label="Hauptnavigation"></nav>'
        '{% block content %}{% endblock %}</body></html>')
    (app/"templates/components.html").write_text(
        '{% macro icon(name,size=20) %}<svg></svg>{% endmacro %}'
        '{% macro csrf_field(csrf) %}<input type="hidden" name="csrf" value="{{csrf}}">{% endmacro %}')
    (app/"templates/studio.html").write_text('{% block content %}Veröffentlichte Videos{% endblock %}')
    # Include the exact prior extension source to test the current admin/live integration.
    shutil.copy(LIVE/"streamly_extension.py",app/"streamly_extension.py")
    for source in (LIVE/"templates").glob("*.html"):
        shutil.copy(source,app/"templates"/source.name)
    schema=app/"schema.sql"
    schema.write_text(schema.read_text()+"\n"+(LIVE/"streamly_schema.sql").read_text())
    (project/".env").write_text("DOMAIN=existing.example\n")
    (project/"compose.local.yaml").write_text("services:\n  web:\n    image: example\n")
    return project

@pytest.fixture
def platform(original_project,tmp_path,monkeypatch):
    installer().install(original_project)
    monkeypatch.setenv("DATA_DIR",str(tmp_path/"data"))
    monkeypatch.setenv("STREAMLY_INTERNAL_SECRET","a"*64)
    monkeypatch.setenv("APP_ENV","development")
    for key in list(sys.modules):
        if key=="app" or key.startswith("app."):monkeypatch.delitem(sys.modules,key,raising=False)
    monkeypatch.syspath_prepend(str(original_project))
    core=importlib.import_module("app.main")
    admin=importlib.import_module("app.streamly_admin")
    setup=importlib.import_module("app.streamly_admin_setup")
    live=importlib.import_module("app.streamly_extension")
    monkeypatch.setattr(live,"media_api",lambda *a,**kw:{"items":[]})
    with TestClient(core.app) as client:
        with core.connect() as db:
            pw=core.ph.hash("normal-user-password-2026")
            db.execute("INSERT INTO users(id,username,email,password_hash,display_name,created_at) VALUES(1,'alice','alice@example.ch',?,'Alice',?)",(pw,core.now()))
            db.execute("INSERT INTO users(id,username,email,password_hash,display_name,created_at) VALUES(2,'bob','bob@example.ch',?,'Bob',?)",(pw,core.now()))
            setup.save_admin(db,"a-real-test-admin-password-2026")
        yield client,core,admin,setup,live

def csrf(client):
    response=client.get("/admin/login")
    assert response.status_code==200
    return re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)

def admin_login(client):
    token=csrf(client)
    response=client.post("/admin/login",data={"csrf":token,"password":"a-real-test-admin-password-2026"},follow_redirects=False)
    assert response.status_code==303
    return token

def owner(client,core,user_id=1):
    raw=secrets.token_urlsafe(32);token=secrets.token_urlsafe(24)
    with core.connect() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)",(core.token_hash(raw),token,user_id,core.now()+86400))
    for cookie in list(client.cookies.jar):
        if cookie.name==core.COOKIE:client.cookies.delete(cookie.name,domain=cookie.domain,path=cookie.path)
    client.cookies.set(core.COOKIE,raw,domain="testserver.local",path="/")
    return token

def add_video(core,user_id=1,title="A video",state=None):
    vid=secrets.token_hex(16)
    with core.connect() as db:
        db.execute("INSERT INTO videos(id,user_id,title,description,category,filename,poster,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (vid,user_id,title,"Description","Gaming",vid+".mp4",vid+".jpg",core.now()))
        if state:
            db.execute("UPDATE streamly_video_moderation SET state=? WHERE video_id=?",(state,vid))
    (core.MEDIA/(vid+".mp4")).write_bytes(b"0123456789"*100)
    (core.MEDIA/(vid+".jpg")).write_bytes(b"test jpeg")
    return vid
