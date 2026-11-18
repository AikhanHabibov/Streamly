"""Install manual moderation into the known StreamNest/Streamly project."""
import argparse
import ast
import datetime
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
MARKER = "# STREAMLY_ADMIN_UPDATE_V1"

def swap(text, old, new, label):
    if old not in text:
        raise ValueError(f"{label}: erwarteter Quelltext fehlt. Keine Dateien geändert. Bitte nicht manuell Sicherheitsprüfungen entfernen.")
    return text.replace(old, new, 1)

def transform_function(source, name, transform):
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name), None)
    if not node:
        raise ValueError(f"Funktion {name} fehlt. Nicht unterstützte Projektversion.")
    lines = source.splitlines(keepends=True)
    old = "".join(lines[node.lineno-1:node.end_lineno])
    new = transform(old)
    lines[node.lineno-1:node.end_lineno] = [new]
    return "".join(lines)

def inject_first(source, name, statement):
    def transform(block):
        tree=ast.parse(block)
        fn=tree.body[0]
        first=fn.body[0]
        line=first.end_lineno if isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant) and isinstance(first.value.value,str) else first.lineno-1
        lines=block.splitlines(keepends=True)
        lines.insert(line, "    "+statement+"\n")
        return "".join(lines)
    return transform_function(source,name,transform)

def prepare(project):
    project=Path(project)
    main_path=project/"app/main.py"
    if not main_path.is_file():
        raise ValueError("app/main.py fehlt. Bitte den vorhandenen Projektordner wählen.")
    main=main_path.read_text(encoding="utf-8-sig")
    changes={}
    if MARKER not in main:
        for anchor in ["def get_videos(", "def require_user(", "async def login(", "def watch(", "def home("]:
            if anchor not in main:
                raise ValueError("Diese Version der Hauptanwendung wird nicht unterstützt.")
        main=inject_first(main,"get_videos",
            'where = (where + " AND " if where else "WHERE ") + "(" + public_video_clause("v") + ")"')
        main=inject_first(main,"require_user","admin_assert_user_active(request)")
        def login_check(block):
            pattern=r'(?m)^([ \t]*)rotate_session\(request, user\["id"\]\)'
            if not re.search(pattern,block):
                raise ValueError("Login-Anker fehlt; Installation abgebrochen.")
            return re.sub(pattern,lambda m:m[1]+'admin_check_login_allowed(request, user["id"])\n'+m[0],block,count=1)
        main=transform_function(main,"login",login_check)
        main=transform_function(main,"watch",lambda block:swap(block,
            '"WHERE v.id!=? ORDER BY (v.category=?) DESC,v.views DESC LIMIT 6"',
            '"WHERE v.id!=? AND " + public_video_clause("v") + " ORDER BY (v.category=?) DESC,v.views DESC LIMIT 6"',
            "Empfehlungen"))
        main=transform_function(main,"home",lambda block:swap(block,
            '"FROM users u WHERE u.username LIKE ? OR u.display_name LIKE ? LIMIT 8"',
            '"FROM users u WHERE (u.username LIKE ? OR u.display_name LIKE ?) AND " + public_creator_clause("u") + " LIMIT 8"',
            "Kanalsuche"))
        main += (
            "\n\n"+MARKER+"\n"
            "from .streamly_admin import (router as streamly_admin_router, public_video_clause, public_creator_clause,\n"
            "    assert_user_active as admin_assert_user_active, check_login_allowed as admin_check_login_allowed,\n"
            "    register_media_guard as register_streamly_admin_guard)\n"
            "app.include_router(streamly_admin_router)\n"
            "register_streamly_admin_guard(app)\n")
    compile(main,str(main_path),"exec")
    changes[main_path]=main.encode()

    live_path=project/"app/streamly_extension.py"
    has_live=live_path.is_file()
    if has_live:
        live=live_path.read_text(encoding="utf-8-sig")
        if "# STREAMLY_ADMIN_LIVE_GUARD_V1" not in live:
            live=inject_first(live,"new_stream_key","admin_assert_stream_allowed(request)")
            # HTTP publish/read authentication must also reject unapproved creator accounts.
            live=transform_function(live,"media_auth",lambda block:swap(block,
                '    if not channel or not channel["key_hash"]:',
                '    if channel and not admin_may_stream(request.state.db, channel["user_id"]):\n'
                '        raise HTTPException(403, "Livestreaming ist nicht freigegeben.")\n'
                '    if not channel or not channel["key_hash"]:',"Streaming-Authentifizierung"))
            live=transform_function(live,"studio_page",lambda block:swap(block,
                'media_available=status is not None)',
                'media_available=status is not None,\n'
                '                       admin_can_stream=admin_may_stream(request.state.db, request.state.user["id"]))',
                "Live-Studio"))
            live += ("\n\n# STREAMLY_ADMIN_LIVE_GUARD_V1\n"
                     "from .streamly_admin import assert_stream_allowed as admin_assert_stream_allowed, may_stream as admin_may_stream\n")
        compile(live,str(live_path),"exec")
        changes[live_path]=live.encode()

    schema_path=project/"app/schema.sql"
    schema=schema_path.read_text(encoding="utf-8-sig")
    if "-- STREAMLY_ADMIN_SCHEMA_V1" not in schema:
        schema += "\n\n-- STREAMLY_ADMIN_SCHEMA_V1\n"+(HERE/"payload/app/streamly_admin_schema.sql").read_text()
        if has_live:
            schema += (
                "\n-- Streaming permissions default to denied; an admin explicitly grants them.\n"
                "UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE NOT EXISTS(\n"
                " SELECT 1 FROM streamly_user_safety s WHERE s.user_id=streamly_live_channels.user_id AND s.blocked=0 AND s.can_stream=1);\n")
    changes[schema_path]=schema.encode()

    base_path=project/"app/templates/base.html"
    base=base_path.read_text(encoding="utf-8-sig")
    if "/static/streamly_admin.css" not in base:
        base=swap(base,"</head>",'<link rel="stylesheet" href="/static/streamly_admin.css">\n</head>',"Basis-Template")
    if 'href="/admin"' not in base:
        base=swap(base,'<nav class="side-nav" aria-label="Hauptnavigation">',
            '<nav class="side-nav" aria-label="Hauptnavigation">\n'
            '{% if request.cookies.get("sl_admin_session") %}<a href="/admin">{{ icon("settings") }}<span>Administration</span></a>{% endif %}',
            "Admin-Navigation")
    changes[base_path]=base.encode()
    studio_path=project/"app/templates/studio.html"
    studio=studio_path.read_text(encoding="utf-8-sig")
    if "sa-creator-note" not in studio:
        studio=swap(studio,"{% block content %}",
            '{% block content %}\n<div class="sa-creator-note">Neue und geänderte Videos benötigen eine Freigabe. '
            '<a href="/studio/moderation">Prüfstatus und Hinweise ansehen →</a></div>',"Creator-Hinweis")
    studio=studio.replace("Veröffentlichte Videos","Videos insgesamt")
    changes[studio_path]=studio.encode()
    live_template_path=project/"app/templates/streamly_live_studio.html"
    if has_live and live_template_path.is_file():
        template=live_template_path.read_text(encoding="utf-8-sig")
        if "sa-live-permission" not in template:
            template=swap(template,"{% block content %}",
                '{% block content %}\n{% if not admin_can_stream %}<div class="sl-notice sa-live-permission">'
                'Livestreaming ist für dein Konto noch nicht freigegeben. Ein Administrator muss es unter '
                '«Benutzer verwalten» ausdrücklich erlauben.</div>{% endif %}',"Live-Freigabehinweis")
        changes[live_template_path]=template.encode()

    for src in (HERE/"payload").rglob("*"):
        if src.is_file():
            changes[project/src.relative_to(HERE/"payload")]=src.read_bytes()
    root_readme=project/"README.md"
    if root_readme.is_file():
        text=root_readme.read_text(encoding="utf-8-sig")
        if "<!-- STREAMLY_ADMIN_README_V1 -->" not in text:
            text=("<!-- STREAMLY_ADMIN_README_V1 -->\n"
                  "> **Admin- und Moderationsupdate aktiv.** Neue/geänderte Videos müssen freigegeben werden; Streaming-Rechte werden separat vergeben.\n"
                  "> Einrichtung und Grenzen: `Streamly_Admin_Update/README.md`. Admin-Anmeldung: `/admin/login`.\n\n")+text
        changes[root_readme]=text.encode()
    for filename in [".gitignore",".dockerignore"]:
        path=project/filename
        text=path.read_text() if path.exists() else ""
        lines=[".env","streamly-admin-backups/"]
        if filename==".dockerignore":
            lines += ["Streamly_Admin_Update/"]
        for line in lines:
            if line not in text.splitlines():
                text += "\n"+line
        changes[path]=(text.rstrip()+"\n").encode()
    return changes,has_live

def install(project):
    project=Path(project).resolve()
    changes,has_live=prepare(project)
    backup=project/"streamly-admin-backups"/datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    manifest=[]
    for path in changes:
        rel=path.relative_to(project)
        existed=path.is_file()
        manifest.append({"path":str(rel),"existed":existed})
        if existed:
            dest=backup/"files"/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,dest)
    (backup/"manifest.json").write_text(json.dumps(manifest,indent=2))
    for path,content in changes.items():
        path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(content)
    print("Streamly-Admin-Code installiert. Dateibackup:",backup.relative_to(project))
    print("Noch kein Admin-Passwort gesetzt. Nach dem Docker-Start die Terminal-Einrichtung ausführen.")
    print("Neue/geänderte Videos sind zunächst privat in der Prüfwarteschlange.")
    if has_live:
        print("Livestream-Rechte werden ab jetzt ausdrücklich im Admin-Bereich freigegeben.")
    return backup

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--project",required=True);args=parser.parse_args()
    try:
        install(args.project)
    except Exception as exc:
        print("Installation abgebrochen:",exc,file=sys.stderr)
        raise SystemExit(1)
