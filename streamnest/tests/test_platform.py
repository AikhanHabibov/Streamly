import importlib
import os
import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MAX_VIDEO_MB", "2")
    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        yield client, module

def token(client, path="/login"):
    response = client.get(path)
    assert response.status_code == 200
    return re.search(r'name="csrf-token" content="([^"]+)"', response.text).group(1)

def register(client, username="creator"):
    csrf = token(client, "/register")
    return client.post("/register", data={
        "csrf": csrf, "username": username, "display_name": username.title(),
        "email": username + "@example.ch", "password": "Ein-sicheres-Passwort-2026"
    }, follow_redirects=False)

def add_video(module, user_id=1, name="test"):
    vid = ("a" if name == "test" else "b") * 32
    with module.connect() as db:
        db.execute("INSERT INTO videos(id,user_id,title,description,category,filename,duration,size,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (vid, user_id, name + " Video", "<script>alert(1)</script>", "Gaming", vid + ".mp4", 10, 100, module.now()))
    (module.MEDIA / (vid + ".mp4")).write_bytes(b"0123456789" * 100)
    return vid

def test_home_headers_and_guest_access(env):
    client, m = env
    home = client.get("/")
    assert home.status_code == 200
    assert "Deine Bühne" in home.text
    assert "default-src 'self'" in home.headers["content-security-policy"]
    assert "HttpOnly" in home.headers["set-cookie"]
    assert "SameSite=lax" in home.headers["set-cookie"]
    assert client.get("/studio").status_code == 401
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/watch/not-real").status_code == 404

def test_registration_login_logout_and_rotation(env):
    c, m = env
    old = token(c)
    old_cookie = c.cookies.get("sn_session")
    assert register(c).status_code == 303
    assert c.cookies.get("sn_session") != old_cookie
    assert c.get("/studio").status_code == 200
    csrf = token(c, "/settings")
    assert csrf != old
    assert c.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert c.get("/studio").status_code == 401
    csrf = token(c)
    assert c.post("/login", data={"csrf": csrf, "username": "creator", "password": "wrong"}).status_code == 400
    result = c.post("/login", data={"csrf": csrf, "username": "creator", "password": "Ein-sicheres-Passwort-2026"}, follow_redirects=False)
    assert result.status_code == 303
    with m.connect() as db:
        hashed = db.execute("SELECT password_hash FROM users").fetchone()[0]
        assert hashed.startswith("$argon2id$")
        assert "Ein-sicheres" not in hashed

def test_csrf_origin_password_and_duplicates(env):
    c, m = env
    assert c.post("/register", data={"username": "x"}).status_code == 403
    csrf = token(c)
    payload = dict(csrf=csrf, username="creator", display_name="Creator", email="test@example.ch", password="short")
    assert c.post("/register", data=payload).status_code == 400
    payload["password"] = "Ein-sicheres-Passwort-2026"
    assert c.post("/register", data=payload, headers={"origin": "https://evil.example"}).status_code == 403
    assert register(c).status_code == 303
    assert register(c).status_code == 400

def test_comments_likes_and_escaping(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c, f"/watch/{vid}")
    body = "<script>alert('xss')</script>"
    assert c.post(f"/watch/{vid}/like", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert c.post(f"/watch/{vid}/comment", data={"csrf": csrf, "body": body}, follow_redirects=False).status_code == 303
    html = c.get(f"/watch/{vid}").text
    assert "&lt;script&gt;" in html
    assert body not in html
    with m.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM likes").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    c.post(f"/watch/{vid}/like", data={"csrf": csrf}, follow_redirects=False)
    with m.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM likes").fetchone()[0] == 0

def test_subscription_feed_and_self_subscription(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c)
    assert c.post("/channel/creator/subscribe", data={"csrf": csrf}).status_code == 400
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    register(c, "viewer")
    csrf = token(c)
    assert "test Video" not in c.get("/subscriptions").text
    assert c.post("/channel/creator/subscribe", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert "test Video" in c.get("/subscriptions").text
    c.post("/channel/creator/subscribe", data={"csrf": csrf}, follow_redirects=False)
    assert "test Video" not in c.get("/subscriptions").text

def test_unique_view_count_and_range_playback(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c)
    for _ in range(2):
        assert c.post(f"/api/videos/{vid}/view", headers={"x-csrf-token": csrf}).json()["views"] == 1
    assert c.post(f"/api/videos/{vid}/view").status_code == 403
    ranged = c.get(f"/media/{vid}", headers={"Range": "bytes=10-19"})
    assert ranged.status_code == 206
    assert ranged.content == b"0123456789"
    assert ranged.headers["content-range"] == "bytes 10-19/1000"
    assert c.get("/media/../../etc/passwd").status_code == 404

def test_edit_profile_and_video_permissions(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c)
    assert c.post("/settings", data={"csrf": csrf, "display_name": "Neuer Name", "bio": "Meine Bio"}, follow_redirects=False).status_code == 303
    assert "Neuer Name" in c.get("/channel/creator").text
    assert c.post(f"/studio/{vid}/edit", data={"csrf": csrf, "title": "Neuer Titel", "description": "Beschreibung", "category": "Wissen"}, follow_redirects=False).status_code == 303
    assert "Neuer Titel" in c.get(f"/watch/{vid}").text
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    register(c, "viewer")
    csrf = token(c)
    assert c.get(f"/studio/{vid}/edit").status_code == 403
    assert c.post(f"/studio/{vid}/delete", data={"csrf": csrf}).status_code == 403
    assert c.post(f"/studio/{vid}/edit", data={"csrf": csrf}).status_code == 403

def test_password_change_revokes_other_sessions(env):
    c, m = env
    register(c)
    csrf = token(c)
    with TestClient(m.app) as other:
        csrf_other = token(other)
        other.post("/login", data={"csrf": csrf_other, "username": "creator", "password": "Ein-sicheres-Passwort-2026"})
        assert other.get("/studio").status_code == 200
        result = c.post("/settings/password", data={"csrf": csrf, "old_password": "Ein-sicheres-Passwort-2026", "password": "Ein-ganz-neues-Passwort-2026"}, follow_redirects=False)
        assert result.status_code == 303
        assert c.get("/studio").status_code == 200
        assert other.get("/studio").status_code == 401

def test_search_filters_and_sql_injection(env):
    c, m = env
    register(c)
    add_video(m)
    assert "test Video" in c.get("/?q=test").text
    assert "test Video" in c.get("/?category=Gaming").text
    assert "test Video" not in c.get("/?category=Musik").text
    assert c.get("/", params={"q": "' OR 1=1 --"}).status_code == 200
    assert "test Video" not in c.get("/", params={"q": "' OR 1=1 --"}).text
    assert c.get("/channel/creator").status_code == 200

def test_upload_rejects_fake_video(env):
    c, m = env
    register(c)
    csrf = token(c, "/upload")
    result = c.post("/upload", data={"csrf": csrf, "title": "Falsches Video", "category": "Gaming"}, files={"video": ("evil.mp4", b"<script>" * 100, "video/mp4")})
    assert result.status_code == 400
    assert list(m.MEDIA.iterdir()) == []

def test_real_upload_thumbnail_playback_edit_delete(env, tmp_path):
    c, m = env
    register(c)
    sample = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=purple:s=320x180:r=24", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(sample)], check=True)
    csrf = token(c, "/upload")
    with sample.open("rb") as video:
        result = c.post("/upload", data={"csrf": csrf, "title": "Mein echtes Video", "description": "Testvideo", "category": "Kreativ"}, files={"video": ("mein-video.mp4", video, "video/mp4")}, follow_redirects=False)
    assert result.status_code == 303
    location = result.headers["location"]
    vid = location.rsplit("/", 1)[1]
    assert c.get(location).status_code == 200
    assert c.get(f"/poster/{vid}").headers["content-type"] == "image/jpeg"
    assert c.get(f"/media/{vid}", headers={"Range": "bytes=0-99"}).status_code == 206
    assert not list(m.MEDIA.glob("*.part"))
    assert c.post(f"/studio/{vid}/delete", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert c.get(location).status_code == 404
    assert not list(m.MEDIA.iterdir())

def test_size_limit_and_host_validation(env):
    c, m = env
    response = c.post("/upload", content=b"x", headers={"content-length": str(100 * 1024**2)})
    assert response.status_code == 413
    assert c.get("/", headers={"host": "evil.example"}).status_code == 400

def test_login_rate_limit(env):
    c, m = env
    csrf = token(c)
    for i in range(11):
        response = c.post("/login", data={"csrf": csrf, "username": "missing", "password": "not-a-valid-password"})
    assert response.status_code == 429

def test_foreign_comment_delete_and_owner_moderation(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c)
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    register(c, "viewer")
    csrf = token(c)
    c.post(f"/watch/{vid}/comment", data={"csrf": csrf, "body": "Mein Kommentar"})
    with m.connect() as db:
        cid = db.execute("SELECT id FROM comments").fetchone()[0]
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    register(c, "stranger")
    csrf = token(c)
    assert c.post(f"/comments/{cid}/delete", data={"csrf": csrf}).status_code == 403
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    csrf = token(c)
    c.post("/login", data={"csrf": csrf, "username": "creator", "password": "Ein-sicheres-Passwort-2026"})
    csrf = token(c)
    assert c.post(f"/comments/{cid}/delete", data={"csrf": csrf}, follow_redirects=False).status_code == 303


def test_account_deletion_and_cascades(env):
    c, m = env
    register(c)
    vid = add_video(m)
    csrf = token(c)
    c.post(f"/watch/{vid}/like", data={"csrf": csrf})
    c.post(f"/watch/{vid}/comment", data={"csrf": csrf, "body": "Test"})
    assert c.post("/settings/delete-account", data={"csrf": csrf, "password": "wrong"}).status_code == 400
    assert c.post("/settings/delete-account", data={"csrf": csrf, "password": "Ein-sicheres-Passwort-2026"}, follow_redirects=False).status_code == 303
    assert c.get("/studio").status_code == 401
    assert c.get(f"/watch/{vid}").status_code == 404
    with m.connect() as db:
        for table in ["users", "likes", "comments", "videos"]:
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert not (m.MEDIA / f"{vid}.mp4").exists()

def test_bad_unicode_csrf_is_403_not_500(env):
    c, _ = env
    token(c)
    assert c.post("/logout", data={"csrf": "🌻"}).status_code == 403

def test_file_size_limit_cleanup(env):
    c, m = env
    register(c)
    csrf = token(c)
    response = c.post("/upload", data={"csrf": csrf, "title": "Zu grosses Video", "category": "Gaming"},
                      files={"video": ("huge.mp4", b"x" * (2 * 1024**2 + 10), "video/mp4")})
    assert response.status_code == 413
    assert not list(m.MEDIA.iterdir())

def test_quota_rejection(env, tmp_path):
    c, m = env
    register(c)
    m.MAX_USER_BYTES = 1
    csrf = token(c)
    response = c.post("/upload", data={"csrf": csrf, "title": "Quota Video", "category": "Gaming"},
                      files={"video": ("file.mp4", b"x" * 200, "video/mp4")})
    assert response.status_code == 413
    assert not list(m.MEDIA.iterdir())
