# Testbericht: Melde-System und Admin-MFA

## Ergebnis

**43 Tests bestanden.** Ausgeführt mit Python 3.13.5, FastAPI 0.128.2,
Starlette 0.50.0, cryptography 46.0.4, qrcode 8.2, HTTPX 0.28.1,
Argon2 und SQLite. JavaScript besteht `node --check`; alle Python-Dateien
wurden erfolgreich kompiliert.

Die Installation auf dem Nutzerrechner kann neuere Versionen innerhalb der
angegebenen Bereiche auflösen. Das ist kein Test dieser künftig aufgelösten
Kombination und keine Aussage über deren vollständigen Sicherheitsstand.

## Testaufbau

Die Original-Projektdateien waren hier nicht mehr verfügbar.
Die Tests erzeugen eine minimale, ausführbare Nachbildung der bekannten
Kern- und Admin-Schnittstellen. Der echte Update-Installer wird darauf
angewendet. Dann laufen die tatsächlich gepatchte Admin-Anmeldung und die
neuen Routen mit echten Cookies, Argon2, Fernet und SQLite.

Medieninhalte sind kleine Testdateien, keine echte Videoverarbeitung.
MediaMTX-Verbindungsabbrüche sind im Adapter ein Stub.

## Geprüft

- Sechs SHA1-Testvektoren aus RFC 6238 mit achtstelliger Ausgabe.
- Passwort allein erstellt keine volle Admin-Sitzung.
- Alte oder gefälschte Passwort-only-Admin-Cookies werden verweigert.
- Erfolgreicher TOTP-Login erstellt einen an die MFA-Generation gebundenen
  Admin-Sitzungsnachweis.
- Verschlüsselter TOTP-Schlüssel und restriktive Rechte der erzeugten
  Schlüsseldatei.
- Falsches Passwort eröffnet keine MFA-Bestätigung.
- Fehlende MFA-Einrichtung scheitert geschlossen.
- Kein erneuter Einsatz eines bereits verwendeten TOTP-Schritts.
- Ablauf der fünfminütigen Passwortbestätigung.
- Passwortwechsel entwertet eine davor ausgestellte Bestätigung.
- Höchstens fünf Codeversuche pro Bestätigung.
- Einmalige, gehashte Wiederherstellungscodes.
- Gleichzeitige Verwendung desselben Wiederherstellungscodes: nur ein Erfolg.
- Gleichzeitige Verwendung desselben TOTP-Codes: nur ein Erfolg.
- CSRF, fremde Origin und gefälschte Bestätigungs-Cookies.
- Geräte-/Code-Reset beendet Sitzungen und ersetzt Wiederherstellungscodes.
- Zeitfenster und Verbrauch des Einrichtungscodes.
- Fehlende Schlüsseldatei verhindert TOTP-Login; gültige Wiederherstellung
  mit zusätzlichem Passwort bleibt möglich.
- Secure-/HttpOnly-/SameSite-Strict-Cookie-Attribute und Challenge-Pfad.
- Keine Einrichtungsschlüssel oder Recovery-Werte in Webseitenantworten.
- Melde-Einsendung, Deduplizierung und eigene Meldestatus-Seite.
- Aktives Konto erforderlich; keine Offenlegung privater fremder Videos.
- CSRF, ungültige Kategorien und inzwischen geänderte Inhalte.
- Admin-Meldeliste nur mit bestätigter MFA.
- Videoentfernung mit Fremdschlüssel-Cascades und physischer Dateibereinigung.
- Meldungen löschen oder sperren Inhalte nicht automatisch.
- Normale Nutzer können keine Moderationsaktionen auslösen.
- Kommentar-Meldungen beziehen sich auf den Kommentarautor, nicht versehentlich
  auf den Besitzer des Videos.
- Wiederverwendete Kommentar-ID: alte Meldung löscht nicht den neuen Kommentar.
- Wiederverwendete Benutzer-ID: altes Verfahren sperrt keine andere Person.
- Live-Meldung: Schlüssel deaktivieren und Streaming-Rechte entziehen.
- Ungültige Moderationsaktionen, CSRF und fremde Origin.
- Wiederaufnahme eines alten Falls mit bereits neuem offenem Fall ergibt
  einen Konflikt statt eines Datenbankfehlers.
- HTML-Escaping und keine Geheimnisse im Audit.
- Installer-Backups, Wiederholbarkeit und unveränderte `.env`.
- Entfernen des alten Passwort-only-Erfolgspfads, nicht nur Umleiten der UI.
- Angepasste Abhängigkeiten und Erweiterung des bekannten Backupskripts.
- Unbekannte Templates/Anmeldefunktionen: Abbruch ohne Quelltextänderungen.
- Zehn unabhängige, zufällige 128-Bit-Wiederherstellungscodes.
- Reporter-Kontolöschung überträgt alte Meldungen nicht an ein neues Konto
  mit derselben ID.
- Konto-Rate-Limit für Meldungen.
- Terminal-Einrichtung mit bestätigtem App-Code, ohne Passwortausgabe.

## Nicht durchgeführt

- Kein tatsächlicher Windows-Doppelklick.
- Kein Docker-Image-Build/-Start: kein Docker-Daemon vorhanden.
- Kein Test des vollständigen Originalprojekts auf dem Nutzerrechner.
- Kein Scan mit einem realen Smartphone-Authenticator.
- Kein öffentlicher Browser-/Cloudflare-/TLS-End-to-End-Test.
- Kein OBS-/MediaMTX-End-to-End-Test.
- Kein Last-, Penetrations- oder unabhängiger Sicherheitsaudit-Test.
- Keine Umsetzung/Prüfung von E-Mail-Zustellung, Virenscanner,
  automatischen externen Backups oder dauerhaftem Hosting.

Die Ergebnisse gelten für die beschriebenen Teilabläufe und sind keine
Garantie für einen vollständig abgesicherten Produktivbetrieb.
