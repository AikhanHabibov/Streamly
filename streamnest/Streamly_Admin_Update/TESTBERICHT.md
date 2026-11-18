# Testbericht: Streamly-Admin-Update

## Ergebnis

**36 Tests erfolgreich.**

Ausgeführt mit Python 3.13, FastAPI/Starlette, HTTPX, Jinja2, Argon2 und SQLite.
Zusätzlich wurden alle Python-Dateien erfolgreich kompiliert.

## Architektur der Prüfung

Die tatsächlichen aktuellen Dateien des Nutzerprojekts waren nicht verfügbar.
Der Installer wurde auf eine ausführbare Rekonstruktion der bekannten
Kernfunktionen angewendet. Darin laufen reale SQLite-Abfragen, echte
Passworthashes, Cookies, Templates und FastAPI-Routen.

Als Live-Komponente wird eine Kopie des zuvor bereitgestellten
`streamly_extension.py` mitgeliefert und tatsächlich durch den neuen Installer
angepasst. Die MediaMTX-API ist simuliert. Diese Tests sind damit stärker als
ein reiner Quelltextvergleich, aber kein Test des vollständigen Originalprojekts.

## Geprüfte Gruppen

- Kein öffentliches Standardpasswort; `12345678` wird abgewiesen.
- Argon2id, separate Admin-Cookies und nur Hashes im Sitzungsspeicher.
- Admin-Session-Rotation, Ablauf, Logout und Widerruf beim Passwort-Reset.
- Secure-/HttpOnly-/SameSite-Strict-Einstellungen.
- Normale Nutzer, auch mit dem Namen `admin`, erhalten keine Admin-Rechte.
- Keine normalen Nutzeraktionen auf geschützten Admin-Routen.
- Neue Videos kommen per Trigger in die Prüfwarteschlange.
- Direkte Watch-, Medien-, Poster- und View-API-Zugriffe werden geprüft.
- Owner/Admin können private Videos ansehen; andere Nutzer nicht.
- HTTP-Range-Zugriff auf private Testdateien ist nur berechtigt möglich.
- Freigeben, Ablehnen und öffentliche Sichtbarkeit.
- Blockierte Creator bleiben trotz eines freigegebenen Videos öffentlich unsichtbar.
- Änderungen an Titel, Beschreibung und Kategorie verlangen erneut eine Prüfung.
- Admin kann Videotitel und öffentliche Anzeigenamen ändern.
- Dauerhafte Video-Löschung mit Fremdschlüssel-Cascades und Datei-Bereinigung.
- CSRF- und Origin-Abweisung auf schreibenden Admin-Routen.
- Kontosperre widerruft Sitzungen und Stream-Schlüssel.
- Gesperrte Konten können sich nicht erneut anmelden oder geschützte Aktionen ausführen.
- Livestreaming ist standardmässig gesperrt und kann ausdrücklich erteilt/entzogen werden.
- Entzug wird auch am internen MediaMTX-Authentifizierungsendpunkt durchgesetzt.
- Öffentliche Suche, Kategorien und Empfehlungen leaken keine privaten Videos.
- Admin-Anmelde-Rate-Limit.
- HTML-Escaping in Titeln, Namen und Änderungsprotokoll.
- Ablehnungsgründe werden im Creator-Bereich nur dem jeweiligen Eigentümer gezeigt.
- Schema-Neustart erhält Prüfzustände; fehlende spätere Moderationszeilen bleiben gesperrt.
- Ungültige Aktionen/Prüfzustände und leere Ablehnungsgründe werden abgewiesen.
- Installer sichert Dateien, ist wiederholbar und ändert `.env` nicht.
- Unbekannter Quelltext wird vor Änderungen abgewiesen.
- Entsperren erteilt Livestream-Rechte nicht automatisch.
- Tatsächliche Teilupload-Routen veröffentlichen nur in die private Prüfwarteschlange.
- In diesem Admin-Testlauf ist die Medienverarbeitung dafür ein Stub:
  Es werden keine echten Codecs mit FFmpeg getestet.
- Änderungsprotokoll enthält keine eingegebenen Passwörter oder Sitzungstokens.
- Basisprojekt ohne Live-Modul wird vom Installer ebenfalls unterstützt.
- Kein Admin-Konto wird allein durch das SQL-Schema erstellt.
- Suchparameter werden nicht als SQL-Code ausgeführt.

## Nicht ausgeführt

- Kein Docker-Build/-Start: keine Docker-Engine in der Prüfungsumgebung.
- Kein Test des Windows-Doppelklick-Installers auf einem echten Windows-Rechner.
- Keine Prüfung der tatsächlich auf dem Nutzerrechner vorhandenen Dateien.
- Kein öffentlicher Cloudflare-, TLS- oder Browser-End-to-End-Test.
- Kein realer OBS-/MediaMTX-Verbindungsabbruch.
- Keine Virenerkennung oder Inhaltsklassifikation.
- Kein Lasttest, Penetrationstest oder unabhängiges Sicherheitsaudit.

Die positiven Ergebnisse gelten für die beschriebenen geprüften Abläufe.
Sie sind keine Garantie gegen alle Sicherheits- oder Betriebsfehler.
