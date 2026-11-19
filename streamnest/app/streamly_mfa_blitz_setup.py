
"""Blitz-compatible, console-only Streamly MFA enrollment."""
import os
import re
import base64
import secrets

from argon2.exceptions import VerificationError, InvalidHashError
from . import main as core
from .streamly_security import match_counter
from .streamly_security_setup import make_codes, save_enrollment, ensure_key


def main():
    password = os.getenv("STREAMLY_ADMIN_PASSWORD", "")
    seed = os.getenv("STREAMLY_MFA_SEED", "").strip().replace(" ", "").upper()
    code = os.getenv("STREAMLY_MFA_CODE", "").strip()

    if not password:
        raise ValueError("STREAMLY_ADMIN_PASSWORD fehlt.")

    core.init_db()
    db = core.connect()

    try:
        account = db.execute(
            "SELECT * FROM streamly_admin_accounts WHERE username='admin'"
        ).fetchone()

        if not account:
            raise ValueError("Admin-Konto nicht gefunden.")

        try:
            core.ph.verify(account["password_hash"], password)
        except (VerificationError, InvalidHashError):
            raise ValueError("Admin-Passwort stimmt nicht.")

        enabled = db.execute(
            "SELECT 1 FROM streamly_mfa WHERE username='admin' AND enabled=1"
        ).fetchone()

        if enabled:
            raise ValueError(
                "MFA ist bereits eingerichtet. Kein Reset durchgeführt."
            )

        # First run: generate a secret.
        if not seed:
            seed = base64.b32encode(
                secrets.token_bytes(20)
            ).decode().rstrip("=")

            print("DEIN MFA-EINRICHTUNGSSCHLÜSSEL:")
            print(seed)
            print("Kopiere ihn sicher. Nicht öffentlich teilen.")
            print("Danach in Blitz STREAMLY_MFA_SEED setzen.")
            return

        # Second run: validate the secret and authenticator code.
        if not re.fullmatch(r"[A-Z2-7]+", seed):
            raise ValueError("MFA-Schlüssel ist ungültig.")

        decoded = base64.b32decode(
            seed + "=" * ((8 - len(seed) % 8) % 8)
        )
        if len(decoded) != 20:
            raise ValueError("MFA-Schlüssel hat eine falsche Länge.")

        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("STREAMLY_MFA_CODE muss sechs Ziffern haben.")

        counter = match_counter(seed, code, core.now())
        if counter is None:
            raise ValueError(
                "MFA-Code ungültig. Smartphone-Uhrzeit prüfen und neuen Code verwenden."
            )

        recovery_codes = make_codes()
        save_enrollment(db, seed, counter, recovery_codes, ensure_key())

        print("MFA erfolgreich eingerichtet!")
        print("WIEDERHERSTELLUNGSCODES - JETZT SICHER SPEICHERN:")
        for recovery_code in recovery_codes:
            print(recovery_code)

        print("Danach die drei temporären Umgebungsvariablen entfernen.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
