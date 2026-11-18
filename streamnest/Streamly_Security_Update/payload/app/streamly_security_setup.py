"""Local console enrollment/reset only. No public MFA-enrollment endpoint."""
import argparse
import base64
import getpass
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode

from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from . import main as core
from .streamly_security import totp, match_counter, key_path, recovery_hash

def ensure_key():
    path=key_path()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not path.exists():
        # Write first, then atomically link: another process can never read a partial key.
        fd,temporary=tempfile.mkstemp(dir=path.parent,prefix=".mfa-key-")
        try:
            with os.fdopen(fd,"wb") as out:
                out.write(Fernet.generate_key());out.flush();os.fsync(out.fileno())
            try:
                os.link(temporary,path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    try:
        return Fernet(path.read_bytes().strip())
    except ValueError:
        raise ValueError("Die vorhandene MFA-Schlüsseldatei ist ungültig. Nicht ungesichert überschreiben; Backup prüfen.")

def make_codes():
    result=[]
    for _ in range(10):
        value=secrets.token_hex(16).upper()
        result.append("-".join(value[i:i+8] for i in range(0,32,8)))
    return result

def provision_uri(seed):
    return "otpauth://totp/"+quote("Streamly:admin",safe="")+"?"+urlencode({
        "secret":seed,"issuer":"Streamly","algorithm":"SHA1","digits":6,"period":30})

def save_enrollment(db,seed,confirmed_counter,codes,fernet):
    from . import streamly_admin as admin
    generation=secrets.token_hex(16)
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO streamly_mfa(username,secret_cipher,generation,last_counter,configured_at) VALUES('admin',?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET secret_cipher=excluded.secret_cipher,generation=excluded.generation,"
            "last_counter=excluded.last_counter,configured_at=excluded.configured_at,enabled=1",
            (fernet.encrypt(seed.encode()).decode(),generation,confirmed_counter,core.now()))
        db.execute("DELETE FROM streamly_mfa_recovery WHERE username='admin'")
        db.executemany("INSERT INTO streamly_mfa_recovery(username,code_hash) VALUES('admin',?)",
                       [(recovery_hash("admin",code),) for code in codes])
        db.execute("DELETE FROM streamly_admin_sessions WHERE username='admin'")
        db.execute("DELETE FROM streamly_mfa_challenges WHERE username='admin'")
        admin.audit(db,"console","admin_mfa_enrolled","admin")
    return generation

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--reset",action="store_true",help="Neues Gerät einrichten; bisherige Codes und Sitzungen werden ungültig")
    args=parser.parse_args()
    core.init_db()
    db=core.connect()
    try:
        account=db.execute("SELECT * FROM streamly_admin_accounts WHERE username='admin'").fetchone()
        if not account:
            raise ValueError("Zuerst das Admin-Konto mit python -m app.streamly_admin_setup einrichten.")
        if db.execute("SELECT 1 FROM streamly_mfa WHERE username='admin' AND enabled=1").fetchone() and not args.reset:
            print("Admin-Zwei-Faktor-Anmeldung ist bereits eingerichtet.")
            print("Bei Geräteverlust im Server-Terminal: python -m app.streamly_security_setup --reset")
            return
        password=getpass.getpass("Bestehendes Admin-Passwort (unsichtbar): ")
        try:
            core.ph.verify(account["password_hash"],password)
        except (VerificationError,InvalidHashError):
            raise ValueError("Admin-Passwort stimmt nicht.")
        seed=base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        uri=provision_uri(seed)
        print("\nAuthenticator-App öffnen und einen neuen zeitbasierten Eintrag hinzufügen.")
        try:
            import qrcode
            qr=qrcode.QRCode(border=2);qr.add_data(uri);qr.make(fit=True);qr.print_ascii(invert=True)
        except (ImportError,UnicodeError):
            print("QR-Darstellung nicht verfügbar. Die manuelle Einrichtung unten funktioniert ebenfalls.")
        print("Manuell: Name Streamly / admin, Typ zeitbasiert (TOTP), 6 Stellen, 30 Sekunden.")
        print("GEHEIMER EINRICHTUNGSSCHLÜSSEL:",seed)
        print("Nicht fotografieren, öffentlich teilen oder in Support-Logs senden.")
        confirmed=None
        for attempt in range(5):
            code=getpass.getpass("Aktueller sechsstelliger Code aus der App: ").strip()
            confirmed=match_counter(seed,code,core.now())
            if confirmed is not None:break
            print("Code nicht erkannt. Automatische Uhrzeit auf Smartphone und Computer prüfen.")
        if confirmed is None:
            raise ValueError("Keine Bestätigung. Bisherige MFA-Konfiguration wurde nicht verändert.")
        codes=make_codes()
        save_enrollment(db,seed,confirmed,codes,ensure_key())
        print("\nMFA eingerichtet. Diese Wiederherstellungscodes JETZT sicher speichern:")
        for code in codes:print(code)
        print("\nJeder Code funktioniert nur einmal und zusätzlich zum Admin-Passwort.")
        print("Sie werden in der Datenbank nur als Hash gespeichert und nicht erneut angezeigt.")
        print("Warte auf den NÄCHSTEN App-Code, bevor du dich anmeldest: der Einrichtungscode ist verbraucht.")
        print("Anmeldung: /admin/login → Passwort → App-Code oder Wiederherstellungscode.")
        print("MFA-Schlüsseldatei zusammen mit der Datenbank vertraulich und verschlüsselt sichern:",key_path())
    finally:
        db.close()

if __name__=="__main__":
    try:
        main()
    except (ValueError,EOFError) as exc:
        print("Einrichtung abgebrochen:",exc)
        raise SystemExit(1)
