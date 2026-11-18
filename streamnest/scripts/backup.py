"""Consistent backup: pause the web service first, then run against its volume."""
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("Aufruf: python scripts/backup.py /pfad/zu/data /pfad/zu/backups")
source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve() / datetime.datetime.now(datetime.timezone.utc).strftime("streamnest-%Y%m%d-%H%M%S")
if not (source / "streamnest.sqlite3").is_file():
    raise SystemExit("Quelldatenbank fehlt.")
if target.is_relative_to(source):
    raise SystemExit("Backup-Ziel muss ausserhalb des Datenverzeichnisses liegen.")
target.mkdir(parents=True, mode=0o700)
with sqlite3.connect(source / "streamnest.sqlite3") as db, sqlite3.connect(target / "streamnest.sqlite3") as backup:
    db.backup(backup)
shutil.copytree(source / "media", target / "media")
# STREAMLY_MFA_BACKUP_V1
if (source / "secrets").is_dir():
    shutil.copytree(source / "secrets", target / "secrets")
print("Backup erstellt:", target)
print("Nur bei pausiertem Schreibbetrieb ist die Kombination aus Datenbank und Videos konsistent.")
