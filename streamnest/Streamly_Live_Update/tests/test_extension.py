import base64
import html
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess

import pytest
import yaml
from conftest import PACKAGE

CSRF = {"x-csrf-token":"test-csrf"}

def initialize(client, size=200, **overrides):
    body = {"filename":"demo.mp4","size":size,"title":"Mein Video","description":"Beschreibung","category":"Gaming", **overrides}
    return client.post("/api/uploads/init",json=body,headers=CSRF)

def create_key(client):
    response = client.post("/studio/live/key",data={"csrf":"test-csrf"})
    assert response.status_code == 200
    key = html.unescape(re.search(r'value="([^"]+)" id="sl-stream-key"',response.text).group(1))
    path, query = key.split("?")
    token = query.split("&pass=")[1]
    return path, token, response

def test_upload_init_auth_csrf_and_metadata(platform):
    c, core, ext = platform
    assert c.post("/api/uploads/init",headers={"x-test-user":""}).status_code == 401
    assert c.post("/api/uploads/init",json={}).status_code == 403
    assert initialize(c,size=core.MAX_VIDEO_BYTES+1).status_code == 413
    assert initialize(c,filename="video.exe").status_code == 400
    assert initialize(c,category="Fake").status_code == 400
    response = initialize(c)
    assert response.status_code == 200
    assert response.json()["chunk_size"] == 8*1024*1024

def test_chunk_sizing_duplicates_and_missing_parts(platform):
    c, core, ext = platform
    ext.CHUNK_SIZE=64
    uid=initialize(c,size=150).json()["id"]
    root=f"/api/uploads/{uid}"
    assert c.put(root+"/chunks/0",content=b"a"*63,headers=CSRF).status_code == 400
    assert c.put(root+"/chunks/0",content=b"a"*65,headers=CSRF).status_code == 413
    assert c.put(root+"/chunks/0",content=b"a"*64,headers=CSRF).status_code == 200
    assert c.put(root+"/chunks/0",content=b"b"*64,headers=CSRF).status_code == 200
    assert (ext.UPLOAD_DIR/uid/"000000.chunk").read_bytes() == b"a"*64
    assert c.get(root+"/status").json()["received"] == [0]
    assert c.post(root+"/finish",headers=CSRF).status_code == 409
    assert c.put(root+"/chunks/3",content=b"a",headers=CSRF).status_code == 400
    assert not list((ext.UPLOAD_DIR/uid).glob("*.tmp"))

def test_upload_ownership_and_cancellation(platform):
    c, core, ext = platform
    uid=initialize(c).json()["id"]
    root=f"/api/uploads/{uid}"
    assert c.get(root+"/status",headers={"x-test-user":"2"}).status_code == 404
    assert c.put(root+"/chunks/0",content=b"a"*200,headers={**CSRF,"x-test-user":"2"}).status_code == 404
    assert c.delete(root,headers={"x-test-user":"2",**CSRF}).status_code == 404
    assert c.delete(root,headers=CSRF).status_code == 200
    assert c.get(root+"/status").status_code == 404
    assert not (ext.UPLOAD_DIR/uid).exists()

def test_quotas_and_three_open_uploads(platform):
    c, core, ext = platform
    core.MAX_USER_BYTES=300
    assert initialize(c,size=200).status_code == 200
    assert initialize(c,size=200).status_code == 413
    core.MAX_USER_BYTES=10000
    assert initialize(c).status_code == 200
    assert initialize(c).status_code == 200
    assert initialize(c).status_code == 409

def test_resume_and_metadata_update(platform):
    c, core, ext = platform
    uid=initialize(c).json()["id"]
    root=f"/api/uploads/{uid}"
    assert c.put(root+"/chunks/0",content=b"x"*200,headers=CSRF).status_code == 200
    assert c.get(root+"/status").json()["received"] == [0]
    assert c.patch(root+"/metadata",json={"title":"Neuer Titel","description":"Neu","category":"Wissen"},headers=CSRF).status_code == 200
    with core.connect() as db:
        meta=json.loads(db.execute("SELECT metadata FROM streamly_uploads WHERE id=?",(uid,)).fetchone()[0])
    assert meta["title"]=="Neuer Titel" and meta["suffix"]==".mp4"
    assert c.patch(root+"/metadata",json={"title":"abc","description":"","category":"X"},headers=CSRF).status_code == 400

def test_expired_upload_is_rejected_and_removed(platform):
    c, core, ext=platform
    uid=initialize(c).json()["id"]
    with core.connect() as db:
        db.execute("UPDATE streamly_uploads SET updated_at=? WHERE id=?",(core.now()-ext.TTL-1,uid))
    assert c.get(f"/api/uploads/{uid}/status").status_code == 404
    assert not (ext.UPLOAD_DIR/uid).exists()

def test_invalid_video_fails_without_publishing(platform):
    c, core, ext=platform
    uid=initialize(c).json()["id"]
    root=f"/api/uploads/{uid}"
    c.put(root+"/chunks/0",content=b"x"*200,headers=CSRF)
    assert c.post(root+"/finish",headers=CSRF).status_code == 202
    assert c.get(root+"/status").json()["state"]=="failed"
    assert not list(core.MEDIA.iterdir())
    assert not (ext.UPLOAD_DIR/uid).exists()

def test_real_ffmpeg_video_chunk_upload_and_thumbnail(platform,tmp_path):
    c, core, ext=platform
    ext.CHUNK_SIZE=512
    source=tmp_path/"source.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=size=320x180:rate=24",
        "-t","1","-c:v","libx264","-pix_fmt","yuv420p","-y",str(source)],check=True)
    body=source.read_bytes()
    uid=initialize(c,size=len(body)).json()["id"]
    root=f"/api/uploads/{uid}"
    for index,start in enumerate(range(0,len(body),ext.CHUNK_SIZE)):
        assert c.put(root+f"/chunks/{index}",content=body[start:start+ext.CHUNK_SIZE],headers=CSRF).status_code==200
    assert c.post(root+"/finish",headers=CSRF).status_code==202
    status=c.get(root+"/status").json()
    assert status["state"]=="done"
    with core.connect() as db:
        video=db.execute("SELECT * FROM videos WHERE id=?",(status["video_id"],)).fetchone()
    assert (core.MEDIA/video["filename"]).is_file()
    assert (core.MEDIA/video["poster"]).is_file()
    assert video["duration"]>0
    assert not (ext.UPLOAD_DIR/uid).exists()
    assert c.post(root+"/finish",headers=CSRF).json()["state"]=="done"

def test_interrupted_background_task_becomes_explicit_failure(platform):
    c, core, ext=platform
    uid=initialize(c).json()["id"]
    with core.connect() as db:
        db.execute("UPDATE streamly_uploads SET state='processing',updated_at=? WHERE id=?",(core.now()-1900,uid))
    status=c.get(f"/api/uploads/{uid}/status").json()
    assert status["state"]=="failed"
    assert "unterbrochen" in status["error"]

def test_stream_keys_are_hashed_and_publish_auth_is_enforced(platform):
    c, core, ext=platform
    path,token,_=create_key(c)
    with core.connect() as db:
        saved=db.execute("SELECT * FROM streamly_live_channels").fetchone()
    assert saved["key_hash"]==ext.digest(token) and token not in saved["key_hash"]
    body={"path":path,"user":"alice","password":token,"action":"publish","protocol":"rtmp"}
    callback="/internal/live-auth"
    auth={"authorization":"Basic "+base64.b64encode(("streamly:"+ext.SECRET).encode()).decode()}
    assert c.post(callback,headers=auth,json=body).status_code==200
    assert c.post("/internal/live-auth",json=body).status_code==403
    assert c.post(callback,headers=auth,json={**body,"password":"wrong"}).status_code==403
    assert c.post(callback,headers=auth,json={**body,"user":"bob"}).status_code==403
    assert c.post(callback,headers=auth,json={**body,"action":"api"}).status_code==403
    assert c.post(callback,headers=auth,json={**body,"action":"read","protocol":"hls","password":""}).status_code==200

def test_key_rotation_and_disable_revoke_previous_path(platform):
    c, core, ext=platform
    old,old_token,_=create_key(c)
    new,new_token,_=create_key(c)
    assert old != new and old_token != new_token
    callback="/internal/live-auth"
    auth={"authorization":"Basic "+base64.b64encode(("streamly:"+ext.SECRET).encode()).decode()}
    assert c.post(callback,headers=auth,json={"path":old,"user":"alice","password":old_token,"action":"publish","protocol":"rtmp"}).status_code==403
    assert c.get("/live/alice").status_code==200
    assert c.post("/studio/live/disable",data={"csrf":"test-csrf"},follow_redirects=False).status_code==303
    assert c.get("/live/alice").status_code==404
    assert c.get(f"/hls/{new}/index.m3u8").status_code==404

def test_live_pages_use_real_ready_state_and_escape_html(platform,monkeypatch):
    c, core, ext=platform
    path,_,_=create_key(c)
    c.post("/studio/live/settings",data={"csrf":"test-csrf","title":"<script>alert(1)</script>","description":"Hallo","category":"Gaming"})
    assert "Alice" not in c.get("/live").text
    monkeypatch.setattr(ext,"media_api",lambda *a,**k:{"items":[{"name":path,"ready":True}]})
    page=c.get("/live")
    assert "Alice" in page.text and "&lt;script&gt;" in page.text
    state=c.get("/api/live/alice/status").json()
    assert state["online"] and state["playlist"]==f"/hls/{path}/index.m3u8"
    assert c.get("/studio/live",headers={"x-test-user":""}).status_code==401

def test_hls_proxy_is_fixed_upstream_and_validates_assets(platform,monkeypatch):
    c, core, ext=platform
    path,_,_=create_key(c)
    urls=[]
    def upstream(url,timeout):
        urls.append(url)
        return io.BytesIO(b"#EXTM3U\nseg123.ts\n")
    monkeypatch.setattr(ext.urllib.request,"urlopen",upstream)
    response=c.get(f"/hls/{path}/index.m3u8")
    assert response.status_code==200
    assert response.headers["cache-control"]=="no-store"
    assert urls==[ext.HLS_URL+f"/{path}/index.m3u8"]
    assert c.get(f"/hls/{path}/secret.txt").status_code==404
    assert c.get("/hls/live_invalid/index.m3u8").status_code==404
    assert c.get(f"/hls/{path}/a..ts").status_code==404

def test_account_deletion_cascades_extension_rows(platform):
    c, core, ext=platform
    create_key(c)
    initialize(c)
    with core.connect() as db:
        db.execute("DELETE FROM users WHERE id=1")
        assert db.execute("SELECT COUNT(*) FROM streamly_live_channels").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM streamly_uploads").fetchone()[0]==0

def load_installer():
    spec=importlib.util.spec_from_file_location("streamly_installer",PACKAGE/"install.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_installer_preserves_configuration_backups_and_is_idempotent(original_project):
    install=load_installer()
    backup=install.install(original_project,skip_vendor=True)
    assert (backup/"files/app/main.py").is_file()
    main=(original_project/"app/main.py").read_text()
    assert main.count("app.include_router(streamly_extension_router)")==1
    assert '"web"' in main and '"/chunks/"' in main and '"/hls/"' in main
    assert "Streamly" in (original_project/"app/templates/base.html").read_text()
    env=(original_project/".env").read_text()
    assert env.startswith("DOMAIN=existing.example")
    assert re.search(r"STREAMLY_INTERNAL_SECRET=[a-f0-9]{64}",env)
    install.install(original_project,skip_vendor=True)
    assert (original_project/"app/main.py").read_text().count("app.include_router(streamly_extension_router)")==1
    assert (original_project/"app/schema.sql").read_text().count("-- STREAMLY_LIVE_SCHEMA_V1")==1
    assert (original_project/".env").read_text()==env
    assert not (original_project/"data").exists()

def test_installer_refuses_unknown_source_without_changing_files(original_project):
    install=load_installer()
    path=original_project/"app/main.py"
    path.write_text("unknown_app = True\n")
    before=path.read_bytes()
    with pytest.raises(ValueError):
        install.install(original_project,skip_vendor=True)
    assert path.read_bytes()==before
    assert not (original_project/"streamly-update-backups").exists()

def test_compose_keeps_sensitive_ports_private():
    compose=yaml.safe_load((PACKAGE/"payload/compose.live.yaml").read_text())
    media=compose["services"]["mediamtx"]
    assert media["ports"]==["127.0.0.1:1935:1935"]
    assert "8888" in media["expose"] and "9997" in media["expose"]
    config=yaml.safe_load((PACKAGE/"payload/streamly-live/mediamtx.yml").read_text())
    assert config["authMethod"]=="http" and config["rtmpEncryption"]=="no"
    assert not config["pathDefaults"]["overridePublisher"]
    assert not config["pathDefaults"]["record"]


def test_live_studio_csrf_and_owner_separation(platform):
    c, core, ext=platform
    create_key(c)
    assert c.post("/studio/live/key",data={"csrf":"wrong"}).status_code==403
    assert c.post("/studio/live/settings",data={"csrf":"test-csrf","title":"Bob sendet","description":"","category":"Musik"},headers={"x-test-user":"2"},follow_redirects=False).status_code==303
    with core.connect() as db:
        alice=db.execute("SELECT title FROM streamly_live_channels WHERE user_id=1").fetchone()[0]
        bob=db.execute("SELECT title FROM streamly_live_channels WHERE user_id=2").fetchone()[0]
    assert alice=="Live mit Alice" and bob=="Bob sendet"

def test_missing_internal_secret_disables_key_creation(platform,monkeypatch):
    c, core, ext=platform
    monkeypatch.setattr(ext,"SECRET","")
    assert c.post("/studio/live/key",data={"csrf":"test-csrf"}).status_code==503

def test_low_disk_rejects_before_creating_reservation(platform,monkeypatch):
    import types
    c, core, ext=platform
    monkeypatch.setattr(ext.shutil,"disk_usage",lambda path:types.SimpleNamespace(free=1))
    assert initialize(c).status_code==507
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM streamly_uploads").fetchone()[0]==0

def test_full_eight_mib_chunk_and_short_final_chunk(platform):
    c, core, ext=platform
    size=ext.CHUNK_SIZE+200
    uid=initialize(c,size=size).json()["id"]
    root=f"/api/uploads/{uid}"
    assert c.put(root+"/chunks/0",content=b"x"*ext.CHUNK_SIZE,headers=CSRF).status_code==200
    assert c.put(root+"/chunks/1",content=b"x"*200,headers=CSRF).status_code==200
    assert c.get(root+"/status").json()["received"]==[0,1]

def test_finalize_rechecks_quota_and_preserves_other_reservations(platform,monkeypatch):
    c, core, ext=platform
    core.MAX_USER_BYTES=400
    uid=initialize(c,size=200).json()["id"]
    assert initialize(c,size=64).status_code==200
    def fake_processing(source,suffix,target,poster):
        target.write_bytes(b"x"*350)
        poster.write_bytes(b"x"*100)
        return 1.0
    monkeypatch.setattr(core,"process_video",fake_processing)
    c.put(f"/api/uploads/{uid}/chunks/0",content=b"x"*200,headers=CSRF)
    c.post(f"/api/uploads/{uid}/finish",headers=CSRF)
    status=c.get(f"/api/uploads/{uid}/status").json()
    assert status["state"]=="failed" and "Kontospeicher" in status["error"]
    assert not list(core.MEDIA.iterdir())
    with core.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]==0

def test_vendor_download_failure_does_not_modify_project(original_project,monkeypatch):
    install=load_installer()
    before=(original_project/"app/main.py").read_bytes()
    def fail():
        raise OSError("offline")
    monkeypatch.setattr(install,"vendor_assets",fail)
    with pytest.raises(OSError):
        install.install(original_project)
    assert before==(original_project/"app/main.py").read_bytes()
    assert not (original_project/"streamly-update-backups").exists()

def test_vendor_assets_are_version_pinned_and_checksummed(monkeypatch):
    import hashlib
    install=load_installer()
    urls=[]
    script=b"/* Hls test fixture, not a real library */"*2000
    def fake_urlopen(url,timeout):
        urls.append(url)
        return io.BytesIO(b"MIT test fixture" if url.endswith("LICENSE") else script)
    monkeypatch.setattr(install.urllib.request,"urlopen",fake_urlopen)
    assets=install.vendor_assets()
    assert all("hls.js@1.7.4/" in u for u in urls)
    assert assets["app/static/vendor/hls.min.js.sha256"].decode().strip()==hashlib.sha256(script).hexdigest()

def test_repeated_finish_does_not_enqueue_duplicate_processing(platform):
    c, core, ext=platform
    uid=initialize(c).json()["id"]
    with core.connect() as db:
        db.execute("UPDATE streamly_uploads SET state='processing' WHERE id=?",(uid,))
    assert c.post(f"/api/uploads/{uid}/finish",headers=CSRF).status_code==202
    with core.connect() as db:
        assert db.execute("SELECT state FROM streamly_uploads WHERE id=?",(uid,)).fetchone()[0]=="processing"


def test_mediamtx_v121_online_state_and_kick_endpoint(platform,monkeypatch):
    c,core,ext=platform
    path,_,_=create_key(c)
    connection_id="11111111-1111-1111-1111-111111111111"
    calls=[]
    def api(path_arg="/v3/paths/list",method="GET"):
        calls.append((path_arg,method))
        if method=="POST":
            return {}
        return {"items":[{"name":path,"online":True,"source":{"type":"rtmpConn","id":connection_id}},
                         {"name":"offline","online":False,"available":True}]}
    monkeypatch.setattr(ext,"media_api",api)
    assert set(ext.live_state())=={path}
    ext.kick_path(path)
    assert ("/v3/rtmp/conns/kick/"+connection_id,"POST") in calls
    assert calls[0][0]=="/v3/paths/list?itemsPerPage=200"
