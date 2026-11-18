"""Patch the known Streamly admin update; do not silently support unknown versions."""
import argparse
import ast
import datetime
import json
from pathlib import Path
import re
import shutil
import sys

HERE=Path(__file__).resolve().parent
MARKER="# STREAMLY_SECURITY_UPDATE_V1"

def replace_once(text,old,new,label):
    if old not in text:
        raise ValueError(f"{label}: erwarteter Quelltext fehlt. Keine Projektdateien geändert.")
    return text.replace(old,new,1)

def transform_function(source,name,transform):
    tree=ast.parse(source)
    node=next((n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name),None)
    if not node:raise ValueError(f"Funktion {name} fehlt. Nicht unterstützte Admin-Version.")
    lines=source.splitlines(keepends=True)
    old="".join(lines[node.lineno-1:node.end_lineno])
    lines[node.lineno-1:node.end_lineno]=[transform(old)]
    return "".join(lines)

def guard_admin_session(block):
    node=ast.parse(block).body[0]
    first=node.body[0]
    idx=first.end_lineno if isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant) and isinstance(first.value.value,str) else first.lineno-1
    lines=block.splitlines(keepends=True)
    lines.insert(idx,"    if not security_admin_session_ok(request, db):\n        return None\n")
    return "".join(lines)

def replace_password_success(block):
    match=re.search(r"(?m)^([ \t]*)raw = secrets.token_urlsafe\(32\)[ \t]*$",block)
    if not match:raise ValueError("Erwartete Passwort-Anmeldung fehlt; kein unsicherer Fallback eingerichtet.")
    # Remove the entire old password-only success path, not just its visible redirect.
    return block[:match.start()]+match[1]+"return security_begin_admin_mfa(request, db, account)\n"

def report_button(text,expression,url,label):
    pattern=re.compile(r'(<button\b[^>]*data-share="\{\{\s*'+re.escape(expression)+r'\s*\}\}"[^>]*>.*?</button>)',re.S)
    if not pattern.search(text):raise ValueError(f"{label}: Teilen-Button nicht gefunden. Keine Dateien geändert.")
    return pattern.sub(lambda m:m[1]+'<a class="button secondary" href="'+url+'">Melden</a>',text,count=1)

def upgrade_dependencies(text):
    additions={"cryptography":"cryptography>=46.0.4,<52","qrcode":"qrcode>=8.2,<9","cffi":"cffi>=2.0.0,<3"}
    lines=text.splitlines()
    for name,requirement in additions.items():
        lines=[line for line in lines if not re.match(r"(?i)^\s*"+re.escape(name)+r"(?:[<=>\[\s;]|$)",line)]
    lines+=["","# Streamly MFA: API-tested minimums; resolve compatible stable releases."]+list(additions.values())
    return "\n".join(lines).rstrip()+"\n"

def prepare(project):
    project=Path(project)
    main_path=project/"app/main.py"
    admin_path=project/"app/streamly_admin.py"
    if not main_path.is_file() or not admin_path.is_file():
        raise ValueError("Das vorherige Streamly-Admin-Update fehlt. Zuerst Admin-Update installieren; danach dieses Paket ausführen.")
    main=main_path.read_text(encoding="utf-8-sig")
    if "# STREAMLY_ADMIN_UPDATE_V1" not in main:
        raise ValueError("Diese Hauptanwendung ist nicht die unterstützte Streamly-Admin-Version.")
    admin=admin_path.read_text(encoding="utf-8-sig")
    changes={}
    if MARKER not in admin:
        for required in ["def admin_session(", "async def login(", "def require_admin(", "def may_preview_video(", "def audit("]:
            if required not in admin:raise ValueError("Nicht unterstützte Admin-Funktionen.")
        admin=transform_function(admin,"admin_session",guard_admin_session)
        admin=transform_function(admin,"login",replace_password_success)
        admin+=("\n\n"+MARKER+"\n"
                "from .streamly_security import admin_session_ok as security_admin_session_ok, begin_admin_mfa as security_begin_admin_mfa\n")
    compile(admin,str(admin_path),"exec");changes[admin_path]=admin.encode()
    if MARKER not in main:
        main+=("\n\n"+MARKER+"\nfrom .streamly_security import router as streamly_security_router\n"
               "app.include_router(streamly_security_router)\n")
    compile(main,str(main_path),"exec");changes[main_path]=main.encode()
    schema_path=project/"app/schema.sql";schema=schema_path.read_text(encoding="utf-8-sig")
    if "-- STREAMLY_SECURITY_SCHEMA_V1" not in schema:
        schema+="\n\n-- STREAMLY_SECURITY_SCHEMA_V1\n"+(HERE/"payload/app/streamly_security_schema.sql").read_text()
    changes[schema_path]=schema.encode()

    base_path=project/"app/templates/base.html";base=base_path.read_text(encoding="utf-8-sig")
    if "/static/streamly_security.css" not in base:
        base=replace_once(base,"</head>",'<link rel="stylesheet" href="/static/streamly_security.css">\n</head>',"Basis-Template")
    if "/static/streamly_security.js" not in base:
        base=replace_once(base,"</head>",'<script defer src="/static/streamly_security.js"></script>\n</head>',"Sicherheits-JavaScript")
    if 'href="/reports/mine"' not in base:
        nav='<nav class="side-nav" aria-label="Hauptnavigation">'
        base=replace_once(base,nav,nav+'\n{% if user %}<a href="/reports/mine">{{ icon("comment") }}<span>Meine Meldungen</span></a>{% endif %}',"Navigation")
    changes[base_path]=base.encode()
    watch_path=project/"app/templates/watch.html";watch=watch_path.read_text(encoding="utf-8-sig")
    if 'href="/report/video/' not in watch:
        watch=report_button(watch,"share_url","/report/video/{{ video.id }}","Videoseite")
    if 'href="/report/comment/' not in watch:
        anchor='<p class="preserve-lines">{{ c.body }}</p>'
        watch=replace_once(watch,anchor,anchor+'<a class="ss-report-link" href="/report/comment/{{ c.id }}">Kommentar melden</a>',"Kommentare")
    changes[watch_path]=watch.encode()
    live_path=project/"app/templates/streamly_live_watch.html"
    if live_path.is_file():
        live=live_path.read_text(encoding="utf-8-sig")
        if 'href="/report/live/' not in live:
            live=report_button(live,"request.url","/report/live/{{ live_channel.username }}","Liveseite")
        changes[live_path]=live.encode()
    nav_path=project/"app/templates/streamly_admin_nav.html";nav=nav_path.read_text(encoding="utf-8-sig")
    if 'href="/admin/reports"' not in nav:
        nav=replace_once(nav,"</nav>",'<a href="/admin/reports">Meldungen</a><a href="/admin/security">Zwei-Faktor-Schutz</a></nav>',"Admin-Navigation")
    changes[nav_path]=nav.encode()
    login_path=project/"app/templates/streamly_admin_login.html";login=login_path.read_text(encoding="utf-8-sig")
    if "ss-mfa-enabled-notice" not in login:
        login=replace_once(login,"{% block content %}",'{% block content %}\n<div class="ss-notice ss-mfa-enabled-notice">Admin-Anmeldung: zuerst Passwort, dann App-Code oder einmaliger Wiederherstellungscode.</div>',"Admin-Anmeldeseite")
    changes[login_path]=login.encode()
    for name in ["requirements.lock","requirements.txt"]:
        path=project/name
        if not path.is_file():raise ValueError(f"{name} fehlt. Nicht unterstützte Projektstruktur.")
        changes[path]=upgrade_dependencies(path.read_text(encoding="utf-8-sig")).encode()

    backup_extended=False
    backup_path=project/"scripts/backup.py"
    if backup_path.is_file():
        text=backup_path.read_text(encoding="utf-8-sig")
        anchor='shutil.copytree(source / "media", target / "media")'
        if "# STREAMLY_MFA_BACKUP_V1" in text:
            backup_extended=True
        elif anchor in text:
            text=text.replace(anchor,anchor+'\n# STREAMLY_MFA_BACKUP_V1\nif (source / "secrets").is_dir():\n    shutil.copytree(source / "secrets", target / "secrets")',1)
            text=text.replace("target.mkdir(parents=True)","target.mkdir(parents=True, mode=0o700)")
            compile(text,str(backup_path),"exec");changes[backup_path]=text.encode();backup_extended=True

    for source in (HERE/"payload").rglob("*"):
        if source.is_file():changes[project/source.relative_to(HERE/"payload")]=source.read_bytes()
    for filename in [".gitignore",".dockerignore"]:
        path=project/filename;text=path.read_text() if path.exists() else ""
        additions=[".env","data/","streamly-security-backups/"]
        if filename==".dockerignore":additions.append("Streamly_Security_Update/")
        for line in additions:
            if line not in text.splitlines():text+="\n"+line
        changes[path]=(text.rstrip()+"\n").encode()
    readme=project/"README.md"
    if readme.is_file():
        text=readme.read_text(encoding="utf-8-sig")
        if "<!-- STREAMLY_SECURITY_README_V1 -->" not in text:
            text=("<!-- STREAMLY_SECURITY_README_V1 -->\n"
                  "> **Melde-System und verpflichtende Admin-MFA installiert.** Terminal-Einrichtung zuerst abschliessen.\n"
                  "> Details und Schlüssel-Backup: `Streamly_Security_Update/README.md`.\n\n")+text
        changes[readme]=text.encode()
    return changes,backup_extended

def install(project):
    project=Path(project).resolve()
    changes,backup_extended=prepare(project)
    backup=project/"streamly-security-backups"/datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    manifest=[]
    for path in changes:
        relative=path.relative_to(project);existed=path.is_file()
        manifest.append({"path":str(relative),"existed":existed})
        if existed:
            target=backup/"files"/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    (backup/"manifest.json").write_text(json.dumps(manifest,indent=2))
    for path,content in changes.items():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    print("Sicherheitsupdate-Code installiert. Dateibackup:",backup.relative_to(project))
    print("Admin-Anmeldung bleibt ohne abgeschlossene Zwei-Faktor-Einrichtung gesperrt.")
    print("Standard-Backupskript mit MFA-Schlüsseln erweitert." if backup_extended else
          "Eigenes Backup prüfen: Datenbank UND MFA-Schlüsseldatei zusätzlich sichern.")
    print("Bestehende Konten, Videos, Passwörter, Volumes und PUBLIC_URL bleiben erhalten.")
    return backup

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--project",required=True);args=parser.parse_args()
    try:install(args.project)
    except Exception as exc:
        print("Installation abgebrochen:",exc,file=sys.stderr);raise SystemExit(1)
