# Technische Primärquellen

- RFC 6238 – Time-Based One-Time Password Algorithm und SHA1-Testvektoren:
  https://www.rfc-editor.org/rfc/rfc6238
- OWASP – Multifactor Authentication:
  https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
- OWASP – Authentication:
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- cryptography – Fernet:
  https://cryptography.io/en/latest/fernet/
- Google Authenticator – Key URI Format:
  https://github.com/google/google-authenticator/wiki/Key-Uri-Format
- SQLite – Transaktionen:
  https://www.sqlite.org/lang_transaction.html
- SQLite – Trigger:
  https://www.sqlite.org/lang_createtrigger.html

TOTP verwendet HMAC-SHA1 nach dem genannten Standard. Für die
Schlüsselverschlüsselung wird Fernet aus cryptography verwendet, keine
selbst entworfene Verschlüsselung. Wiederherstellungscodes sind unabhängige
zufällige 128-Bit-Werte und keine kurzen Passwort-Ersatzwörter.

Die Quellen sind technische Referenzen, keine externe Zertifizierung dieses
Projekts. Test-Fixtures enthalten ausschliesslich bekannte Testdaten, keine
Zugangsdaten oder Einrichtungsschlüssel der echten Webseite.
