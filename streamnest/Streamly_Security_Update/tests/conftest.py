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
PASSWORD="known-test-admin-password-2026"
SEED="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

def installer():
    spec=importlib.util.spec_from_file_location("security_installer",PACKAGE/"install.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.fixture
def original_project(tmp_path):
    project=tmp_path/"project";app=project/"app"
    shutil.copytree(PACKAGE/"tests/fixture_app",app)
    (app/"__init__.py").write_text("")
    (app/"templates").mkdir()
    (app/"templates/base.html").write_text(
        '{% from "components.html" import icon %}<html><head><title>{% block title %}{% endblock %}</title></head>'
        '<body><nav class="side-nav" aria-label="Hauptnavigation"></nav>{% block content %}{% endblock %}</body></html>')
    (app/"templates/components.html").write_text(
        '{% macro icon(name,size=20) %}<svg></svg>{% endmacro %}'
        '{% macro csrf_field(csrf) %}<input type="hidden" name="csrf" value="{{csrf}}">{% endmacro %}')
    (app/"templates/watch.html").write_text(
        '<button class="button" data-share="{{ share_url }}">Teilen</button>'
        '{% for c in comments %}<p class="preserve-lines">{{ c.body }}</p>{% endfor %}')
    (app/"templates/streamly_live_watch.html").write_text(
        '<button data-share="{{ request.url }}">Teilen</button>')
    (app/"templates/streamly_admin_nav.html").write_text('<nav class="sa-tabs"><a href="/admin">Admin</a></nav>')
    (app/"templates/streamly_admin_login.html").write_text(
        '{% extends "base.html" %}{% from "components.html" import csrf_field %}{% block content %}'
        '<form method="post" action="/admin/login">{{csrf_field(csrf)}}<input name="password" type="password"></form>{% endblock %}')
    for name in ["requirements.txt","requirements.lock"]:
        (project/name).write_text("fastapi==0.128.2\ncffi==1.17.1\n")
    (project/".env").write_text("DOMAIN=unchanged.example\n")
    (project/"scripts").mkdir()
    (project/"scripts/backup.py").write_text(
        'import shutil\nfrom pathlib import Path\nsource=Path("data");target=Path("backups/test")\n'
        'target.mkdir(parents=True)\nshutil.copytree(source / "media", target / "media")\n')
    return project

@pytest.fixture
def platform(original_project,tmp_path,monkeypatch):
    installer().install(original_project)
    monkeypatch.setenv("DATA_DIR",str(tmp_path/"data"))
    monkeypatch.delenv("STREAMLY_MFA_KEY_FILE",raising=False)
    for key in list(sys.modules):
        if key=="app" or key.startswith("app."):monkeypatch.delitem(sys.modules,key,raising=False)
    monkeypatch.syspath_prepend(str(original_project))
    core=importlib.import_module("app.main")
    admin=importlib.import_module("app.streamly_admin")
    security=importlib.import_module("app.streamly_security")
    setup=importlib.import_module("app.streamly_security_setup")
    monkeypatch.setattr(core,"now",lambda:1700000100)
    with TestClient(core.app) as client:
        with core.connect() as db:
            db.execute("INSERT INTO users VALUES(1,'alice','Alice',?)",(core.now(),))
            db.execute("INSERT INTO users VALUES(2,'bob','Bob',?)",(core.now(),))
            db.execute("INSERT INTO streamly_admin_accounts VALUES('admin',?,?)",(core.ph.hash(PASSWORD),core.now()))
        codes=setup.make_codes()
        with core.connect() as db:
            setup.save_enrollment(db,SEED,core.now()//30-1,codes,setup.ensure_key())
        yield client,core,admin,security,setup,codes

def csrf(client):
    response=client.get("/admin/login")
    assert response.status_code==200
    return re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)

def password_stage(client,password=PASSWORD):
    token=csrf(client)
    response=client.post("/admin/login",data={"csrf":token,"password":password},follow_redirects=False)
    return token,response

def admin_login(client,core,security,seed=SEED,recovery=None):
    token,response=password_stage(client)
    assert response.status_code==303 and response.headers["location"]=="/admin/mfa"
    if recovery is None:
        with core.connect() as db:
            last=db.execute("SELECT last_counter FROM streamly_mfa WHERE username='admin'").fetchone()[0]
        current=core.now()
        if current//30<=last:
            next_time=(last+1)*30
            core.now=lambda:next_time
        code=security.totp(seed,core.now())
    else:code=recovery
    result=client.post("/admin/mfa",data={"csrf":token,"code":code},follow_redirects=False)
    assert result.status_code==303 and result.headers["location"]=="/admin",result.text
    return token

def owner(client,core,uid=1):
    raw=secrets.token_urlsafe(32);token=secrets.token_urlsafe(24)
    with core.connect() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)",(core.token_hash(raw),token,uid,core.now()+86400))
    for cookie in list(client.cookies.jar):
        if cookie.name==core.COOKIE:client.cookies.delete(cookie.name,domain=cookie.domain,path=cookie.path)
    client.cookies.set(core.COOKIE,raw,domain="testserver.local",path="/")
    return token

def add_video(core,uid=2,state="approved"):
    vid=secrets.token_hex(16)
    with core.connect() as db:
        db.execute("INSERT INTO videos VALUES(?,?,?,'A description','Gaming',?,?,?)",
                   (vid,uid,"A video",vid+".mp4",vid+".jpg",core.now()))
        db.execute("INSERT INTO streamly_video_moderation(video_id,state) VALUES(?,?)",(vid,state))
    (core.MEDIA/(vid+".mp4")).write_bytes(b"test movie")
    (core.MEDIA/(vid+".jpg")).write_bytes(b"test poster")
    return vid

def submit(client,kind,target_id,token,reason="Ein ausführlicher Hinweis für die Moderation."):
    page=client.get(f"/report/{kind}/{target_id}")
    assert page.status_code==200,page.text
    version=re.search(r'name="version" value="([^"]+)"',page.text).group(1)
    return client.post(f"/report/{kind}/{target_id}",data={
        "csrf":token,"version":version,"category":"Spam / Betrug","reason":reason
    },follow_redirects=False)
