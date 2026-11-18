"""Terminal-only administrator creation/reset; never exposes a public setup route."""
import argparse
import getpass
import secrets
from . import main as core

BAD_PASSWORDS = {
    "12345678", "123456789", "password", "admin", "streamly", "qwerty", "letmein",
    "123456789012345", "1234567890123456", "passwordpassword", "adminadminadmin",
    "streamlystreamly", "aaaaaaaaaaaaaaa", "qwertyuiopasdfgh", "letmeinletmeinletmein",
}
def validate_password(password):
    if not 15 <= len(password) <= 128:
        raise ValueError("Bitte 15–128 Zeichen verwenden. 12345678 ist kein geeignetes öffentliches Admin-Passwort.")
    if not password.strip() or password.casefold().strip() in BAD_PASSWORDS:
        raise ValueError("Bitte kein häufiges oder offensichtlich schwaches Passwort verwenden.")

def save_admin(db, password, reset=False):
    validate_password(password)
    exists = db.execute("SELECT 1 FROM streamly_admin_accounts WHERE username='admin'").fetchone()
    if exists and not reset:
        raise ValueError("Admin existiert bereits. Für einen Passwortwechsel --reset verwenden.")
    hashed = core.ph.hash(password)
    with db:
        db.execute(
            "INSERT INTO streamly_admin_accounts(username,password_hash,created_at) VALUES('admin',?,?) "
            "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash", (hashed, core.now()))
        db.execute("DELETE FROM streamly_admin_sessions")
        db.execute(
            "INSERT INTO streamly_admin_audit(actor,action,target,details,created_at) VALUES('console',?,'admin','',?)",
            ("admin_password_reset" if exists else "admin_created", core.now()))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    core.init_db()
    db = core.connect()
    try:
        if db.execute("SELECT 1 FROM streamly_admin_accounts WHERE username='admin'").fetchone() and not args.reset:
            print("Admin ist bereits eingerichtet. Benutzername: admin")
            print("Für einen Passwortwechsel: python -m app.streamly_admin_setup --reset")
            return
        print("Admin separat einrichten. Benutzername: admin")
        print("Eigenes Passwort: mindestens 15 Zeichen. Leer lassen erzeugt ein zufälliges Passwort.")
        password = getpass.getpass("Admin-Passwort (Eingabe unsichtbar): ")
        generated = not password
        if generated:
            password = secrets.token_urlsafe(24)
        elif password != getpass.getpass("Passwort wiederholen: "):
            raise ValueError("Die Passwörter stimmen nicht überein.")
        save_admin(db, password, reset=args.reset)
        print("Admin eingerichtet. Anmeldung auf deiner Webseite unter /admin/login")
        if generated:
            print("Einmalig angezeigtes Passwort:", password)
            print("Jetzt im Passwortmanager speichern. Nicht öffentlich teilen oder fotografieren.")
    finally:
        db.close()

if __name__ == "__main__":
    try:
        main()
    except (ValueError, EOFError) as exc:
        print("Admin-Einrichtung abgebrochen:", exc)
        raise SystemExit(1)
