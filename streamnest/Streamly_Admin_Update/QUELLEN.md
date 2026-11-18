# Technische Primärquellen

Leitlinien, keine externe Zertifizierung dieses Projekts:

- OWASP – Authorization: serverseitig pro Request prüfen, standardmässig verweigern.
  https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- OWASP – Authentication: Passwortlänge, Anmeldebegrenzung und sensible Konten.
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- OWASP – Password Storage: Argon2id und sichere Passwortspeicherung.
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- OWASP – File Upload: getrennte technische Datei- und Inhaltsprüfung;
  eine manuelle Prüfwarteschlange ist kein vollständiger Virenschutz.
  https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP – CSRF Prevention:
  https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- SQLite – Trigger:
  https://www.sqlite.org/lang_createtrigger.html
- SQLite – Fremdschlüssel:
  https://www.sqlite.org/foreignkeys.html

Die mitgelieferten Test-Fixtures bilden den bekannten Anwendungskern und den
zuvor erstellten Live-Code nach. Sie enthalten nur Testzugangsdaten, keine
Zugangsdaten der tatsächlichen Webseite.
