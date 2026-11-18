'''Run from a temporary Python container; no local Python installation required.'''
import argparse
import datetime
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
MARKER = "# STREAMLY_LIVE_UPDATE_V1"
NAV = r'''
    <a href="/live" class="sl-nav-link">{{ icon('play') }}<span>Jetzt live</span></a>
    <a href="{{ '/studio/live' if user else '/login' }}">{{ icon('upload') }}<span>Livestream Studio</span></a>
'''

def replace_once(text, old, new, label):
    if old not in text:
        raise ValueError(f"{label}: erwarteter Quelltext fehlt. Keine Dateien geändert. Diese Version passt nicht zu deinem Projekt.")
    return text.replace(old, new, 1)

def prepare(project):
    main_path = project / "app/main.py"
    if not main_path.is_file():
        raise ValueError("Projektordner nicht gefunden: app/main.py fehlt.")
    main = main_path.read_text(encoding="utf-8-sig")
    changes = {}
    if MARKER not in main:
        required = ["def require_user(", "def csrf_check(", "def process_video(", "class BodyLimit:", "def connect(", "def field("]
        if any(word not in main for word in required):
            raise ValueError("Dieses Update benötigt die ursprünglich bereitgestellte StreamNest/Streamly-FastAPI-App.")
        main = replace_once(
            main,
            'allowed_hosts=[urlsplit(PUBLIC_URL).hostname] if PRODUCTION else ["localhost", "127.0.0.1", "testserver"],',
            'allowed_hosts=[urlsplit(PUBLIC_URL).hostname, "web"] if PRODUCTION else ["localhost", "127.0.0.1", "testserver", "web"],',
            "TrustedHost-Konfiguration")
        old = 'limit = MAX_VIDEO_BYTES + 2 * 1024 * 1024 if scope["path"] == "/upload" else 128 * 1024'
        main = replace_once(main, old, old + '\n        if scope["path"].startswith("/api/uploads/") and "/chunks/" in scope["path"]:\n            limit = 9 * 1024 * 1024', "Request-Limit")
        main = replace_once(main,
            'request.url.path.startswith(("/media/", "/poster/", "/health"))',
            'request.url.path.startswith(("/media/", "/poster/", "/health", "/hls/", "/internal/live-auth"))',
            "Sitzungsmiddleware")
        main = replace_once(main,
            'response.headers["Cache-Control"] = "no-store" if needs_session else "private, max-age=300"',
            'response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store" if needs_session else "private, max-age=300")',
            "Cache-Middleware")
        main = re.sub(r'os.getenv\("MAX_VIDEO_MB", "\d+"\)', 'os.getenv("MAX_VIDEO_MB", "2048")', main)
        main = re.sub(r'os.getenv\("USER_QUOTA_MB", "\d+"\)', 'os.getenv("USER_QUOTA_MB", "20480")', main)
        main += "\n\n" + MARKER + "\nfrom .streamly_extension import router as streamly_extension_router\napp.include_router(streamly_extension_router)\n"
    # Visible branding only. Internal DB paths, volume names, cookies and account data stay unchanged.
    main = main.replace("StreamNest", "Streamly").replace("Stramly", "Streamly")
    compile(main, str(main_path), "exec")
    changes[main_path] = main.encode()

    schema_path = project / "app/schema.sql"
    schema = schema_path.read_text(encoding="utf-8-sig")
    if "-- STREAMLY_LIVE_SCHEMA_V1" not in schema:
        schema += "\n\n-- STREAMLY_LIVE_SCHEMA_V1\n" + (HERE / "payload/app/streamly_schema.sql").read_text()
    changes[schema_path] = schema.encode()

    base_path = project / "app/templates/base.html"
    base = base_path.read_text(encoding="utf-8-sig")
    if "/static/streamly_extension.css" not in base:
        base = replace_once(base, "</head>", '<link rel="stylesheet" href="/static/streamly_extension.css">\n<script defer src="/static/streamly_uploads.js"></script>\n</head>', "Basis-Template")
    if 'class="sl-nav-link"' not in base:
        nav_start = '<nav class="side-nav" aria-label="Hauptnavigation">'
        base = replace_once(base, nav_start, nav_start + NAV, "Navigation")
    base = base.replace("StreamNest", "Streamly").replace("STREAMNEST", "STREAMLY").replace("Stramly", "Streamly")
    base = base.replace("stream<span>nest</span>", "stream<span>ly</span>")
    base = base.replace("Stram<span>ly</span>", "stream<span>ly</span>")
    changes[base_path] = base.encode()

    studio_path = project / "app/templates/studio.html"
    studio = studio_path.read_text(encoding="utf-8-sig")
    if "sl-studio-links" not in studio:
        studio = replace_once(studio, "{% block content %}",
            '{% block content %}\n<div class="sl-studio-links"><a class="button secondary" href="/studio/live">Livestream Studio →</a><a class="button secondary" href="/live">Jetzt live entdecken →</a></div>',
            "Creator Studio")
    changes[studio_path] = studio.encode()

    for source in (HERE / "payload").rglob("*"):
        if source.is_file():
            changes[project / source.relative_to(HERE / "payload")] = source.read_bytes()
    # Update remaining visible titles without touching stored data or internal identifiers.
    for template in (project / "app/templates").glob("*.html"):
        if template not in changes:
            text = template.read_text(encoding="utf-8-sig")
            updated = text.replace("StreamNest", "Streamly").replace("Stramly", "Streamly")
            if updated != text:
                changes[template] = updated.encode()
    root_readme = project / "README.md"
    if root_readme.is_file():
        old_readme = root_readme.read_text(encoding="utf-8-sig")
        if "<!-- STREAMLY_LIVE_README_V1 -->" not in old_readme:
            note = ("<!-- STREAMLY_LIVE_README_V1 -->\n"
                    "> **Streamly-Live-Update installiert.** Die ursprüngliche Anleitung unten beschreibt den alten Stand.\n"
                    "> Neu: Livestreams, Teiluploads bis 2 GiB und 20 GiB Kontospeicher.\n"
                    "> Ab jetzt mit `docker compose -f compose.local.yaml -f compose.live.yaml up -d` starten.\n"
                    "> Details, Grenzen und OBS-Anleitung: `Streamly_Live_Update/README.md`.\n\n")
            changes[root_readme] = (note + old_readme).encode()
    env_path = project / ".env"
    env = env_path.read_text(encoding="utf-8-sig") if env_path.exists() else ""
    match = re.search(r"^STREAMLY_INTERNAL_SECRET=(.*)$", env, re.MULTILINE)
    if match:
        if not re.fullmatch(r"[a-f0-9]{64}", match.group(1).strip()):
            raise ValueError("Vorhandenes STREAMLY_INTERNAL_SECRET ist nicht im erwarteten Format. Bitte sichere die .env und entferne nur diese Variable, bevor du erneut installierst.")
    else:
        env += "\n# Streamly Live: intern, niemals öffentlich teilen.\nSTREAMLY_INTERNAL_SECRET=" + secrets.token_hex(32) + "\n"
    changes[env_path] = env.encode()
    for filename, lines in {
        ".gitignore": [".env", "streamly-update-backups/", "app-before-streamly/"],
        ".dockerignore": [".env", "streamly-update-backups/", "app-before-streamly/", "Streamly_Live_Update/"]
    }.items():
        path = project / filename
        text = path.read_text() if path.exists() else ""
        for line in lines:
            if line not in text.splitlines():
                text += "\n" + line
        changes[path] = (text.rstrip() + "\n").encode()
    return changes

def vendor_assets():
    base = "https://cdn.jsdelivr.net/npm/hls.js@1.7.4/"
    with urllib.request.urlopen(base + "dist/hls.min.js", timeout=90) as response:
        script = response.read(3 * 1024 * 1024)
    if len(script) < 50000 or b"Hls" not in script:
        raise ValueError("Der hls.js-Download ist ungültig; keine Projektdateien geändert.")
    with urllib.request.urlopen(base + "LICENSE", timeout=30) as response:
        license_text = response.read(64 * 1024)
    return {
        "app/static/vendor/hls.min.js": script,
        "app/static/vendor/hls.LICENSE.txt": license_text,
        "app/static/vendor/hls.min.js.sha256": (hashlib.sha256(script).hexdigest() + "\n").encode()
    }

def install(project, skip_vendor=False):
    project = Path(project).resolve()
    changes = prepare(project)
    if not skip_vendor:
        for name, data in vendor_assets().items():
            changes[project / name] = data
    else:
        print("TESTMODUS: hls.js wird nicht heruntergeladen.")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = project / "streamly-update-backups" / stamp
    backup.mkdir(parents=True)
    manifest = {"files": []}
    for path in changes:
        rel = path.relative_to(project)
        existed = path.is_file()
        manifest["files"].append({"path": str(rel), "existed": existed})
        if existed:
            copy = backup / "files" / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
    import json
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (backup / "README.txt").write_text(
        "Dateibackup vor dem Streamly-Live-Update. Enthält ggf. die alte .env: vertraulich behandeln.\n"
        "Die Datenbank und Docker-Volumes wurden nicht geändert oder gesichert.\n"
        "Wiederherstellung: Dateien unter files an die ursprüngliche Stelle zurückkopieren;\n"
        "neu hinzugefügte Dateien anhand manifest.json entfernen. Danach Image neu bauen.\n")
    try:
        for path, data in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    except OSError:
        print("Schreibfehler. Backup liegt in:", backup)
        raise
    print("Streamly-Live-Update installiert.")
    print("Sicherung der bisherigen Projektdateien:", backup.relative_to(project))
    print("Konten, Video-Dateien, Datenbanknamen und Docker-Volumes bleiben unverändert.")
    print("Start: docker compose -f compose.local.yaml -f compose.live.yaml up --build -d")
    return backup

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--skip-vendor", action="store_true", help="Nur für automatisierte Tests, nicht für die echte Installation")
    args = parser.parse_args()
    try:
        install(args.project, skip_vendor=args.skip_vendor)
    except Exception as exc:
        print("Installation abgebrochen:", exc, file=sys.stderr)
        sys.exit(1)
