# Streamly: Admin und Moderation

Update für die bekannte StreamNest/Streamly-FastAPI-Anwendung,
optional mit dem zuvor bereitgestellten Livestream-Update.

**Dieses Paket installiert Code. Auf deiner Webseite ist es erst nach der
Installation aktiv. Das Admin-Konto wird danach im Terminal eingerichtet.**

## 1. Installation unter Windows

### Einzelne CMD-Datei – empfohlen

1. `Streamly_Admin_Installieren.cmd` herunterladen.
2. Direkt in den bisherigen `streamnest`-Projektordner legen,
   neben `compose.local.yaml` und den Ordner `app`.
3. Docker Desktop starten.
4. Die Datei doppelt anklicken.
5. Nach dem Neubau fragt das Terminal nach dem Admin-Passwort:
   - **Benutzername:** `admin`
   - **Passwort:** selbst wählen, 15–128 Zeichen.
   - Die Eingabe wird nicht angezeigt. Das ist beabsichtigt.
   - Alternativ leer lassen und Enter drücken: Es entsteht ein zufälliges
     Passwort, das genau einmal im Fenster angezeigt wird.
6. Passwort sicher speichern. Nicht in Chats oder Screenshots teilen.
7. Das bisherige Cloudflare-Fenster offen lassen und die Webseite mit
   **Ctrl + F5** aktualisieren.

Es wird **kein öffentliches Standardpasswort `12345678`** eingerichtet.
Das Passwort ist zu kurz für die hier vorgesehene öffentliche Admin-Anmeldung.
Die begrenzte lokale Liste häufig verwendeter Passwörter ersetzt keine
vollständige Prüfung gegen geleakte Passwörter.

Die einzelne CMD-Datei enthält dieses Paket als ZIP-Daten. PowerShell entpackt
es lokal und startet den offen einsehbaren Installer. Keine
PowerShell-Ausführungsrichtlinie wird geändert, keine Firewall-Regel angelegt.
Bei verwalteten Schul-/Arbeitsrechnern bestehende Sicherheitsregeln nicht umgehen.

### ZIP-Alternative

Den Ordner `Streamly_Admin_Update` aus dem ZIP in deinen Projektordner kopieren
und darin `INSTALLIEREN.cmd` öffnen:

```text
streamnest/
├── app/
├── compose.local.yaml
├── compose.live.yaml             # falls das Live-Update installiert ist
└── Streamly_Admin_Update/
    ├── INSTALLIEREN.cmd
    ├── install.py
    ├── payload/
    └── README.md
```

Keine lokale Python-Installation nötig. Die Installation verwendet ein
temporäres Python-Docker-Image. Die vorhandenen Python-Abhängigkeiten reichen
für den neuen Code aus.

Der Installer bricht bei abweichenden erwarteten Quelltext-Stellen ab, bevor
Projektdateien geändert werden. Wenn das passiert, die Fehlermeldung schicken,
nicht die Prüfungen aus dem Skript entfernen.

## 2. Admin anmelden

Öffne deine **aktuelle öffentliche Webseitenadresse** mit `/admin/login` am Ende:

```text
https://deine-aktuelle-adresse.trycloudflare.com/admin/login
```

- Benutzername: **admin**
- Passwort: dein selbst gesetztes oder einmalig angezeigtes Passwort.

Das ist ein **separates Administratorkonto**. Es wird nicht über die normale
Registrierung erstellt. Ein gewöhnliches Nutzerkonto namens `admin` hat keine
Admin-Rechte. Dein normales Creator-Konto kannst du weiterhin getrennt benutzen.

Im Admin-Bereich gibt es drei Bereiche:
- **Videos prüfen**
- **Benutzer verwalten**
- **Änderungsprotokoll**

Eine Admin-Sitzung gilt höchstens vier Stunden. Beim erneuten Anmelden wird
das Sitzungstoken ersetzt; nach einem Passwort-Reset werden alle bisherigen
Admin-Sitzungen widerrufen. Es gibt in diesem Paket noch keine Zwei-Faktor-
Authentifizierung.

## 3. Videos prüfen, bearbeiten und löschen

### Neue und geänderte Videos

Neue Uploads werden zunächst mit **«Prüfung offen»** gespeichert.
Sie sind dann nur für ihren Creator und einen angemeldeten Admin sichtbar.
Normale Besucher können sie auch nicht über direkte Video-, Poster- oder
Player-Links abrufen.

Diese Regel gilt sowohl für den bisherigen Direkt-Upload als auch für die
Teiluploads aus dem Live-Update. Ein SQLite-Trigger setzt den Status im selben
Datenbankvorgang wie den Videoeintrag.

Wenn Titel, Beschreibung oder Kategorie tatsächlich geändert werden, wird
das Video wieder auf **«Prüfung offen»** gesetzt. Dadurch kann ein Creator
nicht einfach einen freigegebenen Titel nachträglich ersetzen und die
Prüfung umgehen.

### Admin-Aktionen

- Video ansehen und die technischen Dateien im bestehenden Player prüfen.
- Videotitel, Beschreibung und Kategorie ändern.
- Video **freigeben**, **ablehnen** oder zur erneuten Prüfung zurückstellen.
- Bei Ablehnung einen Grund angeben.
- Video dauerhaft löschen. Zugehörige Likes und Kommentare werden durch
  die bestehenden Fremdschlüssel entfernt; Video und Poster werden aus dem
  Medienverzeichnis gelöscht.
- Entscheidungen im Änderungsprotokoll nachvollziehen.

Auch ein vom Admin geänderter Videotitel setzt die Prüfung zurück. Nach dem
Speichern bei Bedarf auf **«Freigeben»** klicken.

Wenn das Löschen einer Mediendatei am Dateisystem scheitert, bleibt sie nicht
öffentlich abrufbar: Der Video-Datenbankeintrag ist entfernt. Das Problem wird
als Bereinigungswarnung protokolliert und muss am Server behoben werden.

### Bereits vorhandene Videos

Bei der **ersten** Installation behalten bisherige Videos ihre öffentliche
Sichtbarkeit und werden als freigegeben übernommen. Du kannst sie unter
«Alle» prüfen, ablehnen oder löschen. Es findet keine nachträgliche
automatische Inhaltsprüfung statt.

Ein fehlender Moderationsdatensatz nach dieser ersten Übernahme wird nicht
bei jedem Neustart automatisch freigegeben; der Zugriff bleibt dann gesperrt.

### Creator-Hinweise

Unter `/studio/moderation` sieht ein Creator den Status und den Hinweis zu
seinen eigenen neuesten 200 Videos. Die Gründe anderer Creator sind dort
nicht sichtbar.

## 4. Benutzer verwalten

Unter `/admin/users` kannst du:

- Den öffentlichen **Anzeigenamen** eines Creators ändern.
- Ein Benutzerkonto mit Grund sperren und wieder entsperren.
- Livestreaming ausdrücklich erlauben oder entziehen.

**Der Login-Benutzername und bestehende Kanal-URLs werden nicht umbenannt.**
So bleiben öffentliche Links stabil. Ein aktiver Nutzer kann seinen Anzeigenamen
weiterhin selbst bearbeiten; bei wiederholtem Missbrauch das Konto sperren.

Eine Sperre:
- beendet die bestehenden normalen Benutzer-Sitzungen,
- verhindert eine erneute erfolgreiche Anmeldung,
- verhindert geschützte Aktionen mit einer noch erkannten alten Sitzung,
- blendet Videos und Kanal des Kontos öffentlich aus,
- deaktiviert den Stream-Schlüssel und die öffentliche Live-Wiedergabe.

Das betrifft nur dieses Konto. Es ist keine IP-, Geräte- oder Identitätssperre.
Eine Neuregistrierung lässt sich damit nicht vollständig verhindern.

## 5. Wichtig für Livestreams

**Nach diesem Update ist Livestreaming standardmässig gesperrt,
bis du es pro Creator erlaubst.** Das gilt auch für bestehende Creator.

1. Als Admin unter `/admin/users` den gewünschten Creator suchen.
2. **«Streaming erlauben»** anklicken.
3. Mit dem normalen Creator-Konto im Live-Studio einen neuen Schlüssel erstellen.
4. OBS mit diesem Schlüssel verbinden.

Das Entziehen der Erlaubnis oder eine Kontosperre entwertet den Schlüssel
und blockiert die Wiedergabe über Streamly. Die Anwendung versucht zusätzlich,
eine bereits laufende RTMP-Verbindung über die interne MediaMTX-API zu beenden.
Dieser letzte Schritt hängt von der Erreichbarkeit des Mediendienstes ab.

Ein Livebild kann nicht vorab als komplettes Video geprüft werden. Es gibt keine
automatische Erkennung problematischer Szenen oder Töne und keine pauschale
Garantie, dass erlaubte Creator sich korrekt verhalten.

Das Entsperren eines Kontos erteilt Streaming-Rechte nicht automatisch neu.

## 6. Passwort später setzen oder zurücksetzen

Falls die Eingabe beim Installieren abgebrochen wurde, in PowerShell im
Projektordner ausführen:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_admin_setup
```

Falls das Live-Update nicht installiert ist, `-f compose.live.yaml` weglassen.

Für ein neues Passwort:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_admin_setup --reset
```

Oder `Streamly_Admin_Update/ADMIN_PASSWORT_AENDERN.cmd` öffnen.

Es werden keine Passwörter über Kommandozeilenargumente oder Umgebungsvariablen
übergeben. Das Terminal fragt sie verdeckt ab. Ein Reset beendet alle
Admin-Sitzungen, nicht die normalen Benutzerkonten.

## 7. Was unverändert bleibt

- Projektordner, Datenbankpfad, Cookie der normalen Anmeldung und Docker-Volumes.
- Bestehende Benutzer, Videos, Profile, Kommentare und Abonnements.
- Deine bisherige `PUBLIC_URL`.
- Die Cloudflare-Konfiguration und die OBS-Serveradresse.
- Vorhandene Upload-Grössen und technische Dateiformatprüfung.

Der Installer ändert `.env` nicht. Nach dem Live-Update immer beide
Compose-Dateien zum Starten verwenden:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml up -d
```

Nach Codeänderungen `--build` ergänzen. Keine Daten mit `down -v` löschen.

## 8. Sicherheitsmassnahmen und Grenzen

Enthalten:
- Getrennte Admin-Anmeldung, kein öffentliches Registrieren von Admin-Rechten.
- Argon2id-Passworthashes und gehashte zufällige Admin-Sitzungstokens.
- HttpOnly-/SameSite-Strict-Admin-Cookie, bei `APP_ENV=production` zusätzlich Secure.
- Anmeldung mit begrenzter Versuchszahl über die bestehende Rate-Limit-Funktion.
- CSRF- und Origin-Prüfung auf schreibenden Admin-Routen.
- Serverseitige Berechtigungsprüfung, parametrisierte SQL-Abfragen und
  HTML-Escaping.
- Direkte Medienzugriffe werden ebenfalls geprüft; es werden nicht nur
  Buttons versteckt.
- `no-store` auf neu ausgelieferten Video-/Poster-Antworten durch den Guard.
- Protokoll für Login-Versuche, Änderungen und Moderationsentscheidungen.
- Keine Passwort- oder Sitzungstokenwerte im Änderungsprotokoll.

**Nicht enthalten oder nicht garantiert:**
- Kein vollständiger Schutz gegen Viren oder Schwachstellen in FFmpeg/Browsern.
- Kein Antiviren-Dienst, automatischer Inhaltsklassifikator oder Urheberrechtsfilter.
- Keine Zwei-Faktor-Authentifizierung und kein professionelles Sicherheitsaudit.
- Kein umfassender Schutz gegen DDoS, gestohlene Endgeräte oder kompromittierte Server.
- Ein Admin kann sich bei der manuellen Prüfung irren.
- Bereits übertragene, heruntergeladene oder extern kopierte Inhalte kann eine
  spätere Sperre nicht zurückholen. Bereits offene Übertragungen lassen sich
  nicht rückwirkend ungeschehen machen.
- Neue Uploads werden auf deinem Server gespeichert, auch wenn sie zunächst
  nicht öffentlich sichtbar sind. Eine Prüfwarteschlange verhindert nicht,
  dass ungeeignete Daten überhaupt beim Betreiber ankommen.
- Logs und Datenbank müssen betrieblich geschützt und gesichert werden.

Es ist eine zusätzliche Moderations- und Zugriffsschutzschicht, kein Nachweis
eines vollständig abgesicherten Internetdienstes. Sicherheitsupdates, Backups,
Betriebsüberwachung und ein tatsächliches Prüf-/Meldeverfahren bleiben nötig.

## 9. Backups und Rücknahme

Geänderte Projektdateien liegen vorher gesichert in:

```text
streamly-admin-backups/<Zeitstempel>/files/
```

`manifest.json` verzeichnet die ursprünglichen und neu angelegten Dateien.
Dies ist **kein Datenbank- oder Video-Backup**. Sichere deine Daten zusätzlich
mit der ursprünglichen Backup-Anleitung, insbesondere vor Schemaänderungen.

Nach dem ersten Start enthält SQLite neue Admin-/Moderationstabellen und
Trigger. Für einen Rollback genügt deshalb nicht immer nur das Zurückkopieren
der Python-Dateien. Dienste stoppen, Daten und Dateien sichern und einen
konsistenten Rückstand wiederherstellen. Nicht ungesichert einzelne
Berechtigungstabellen oder Trigger aus einer laufenden Datenbank entfernen.

Das Löschen von Videos durch einen Admin kann nur aus einem passenden Backup
rückgängig gemacht werden. Eine solche Wiederherstellung spielt gegebenenfalls
auch andere ältere Daten zurück.

## Wenn die Seite nach dem Update einen Fehler zeigt

Im Projektordner:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml ps
docker compose -f compose.local.yaml -f compose.live.yaml logs --tail=60 web
```

Ohne Live-Update den entsprechenden `-f compose.live.yaml`-Teil weglassen.
Nur Fehlermeldungen weitergeben, keine Passwörter, Cookies oder `.env`-Dateien.

## 10. Tests und technische Dateien

**36 automatisierte Tests bestanden.** Details: `TESTBERICHT.md`.

Die ursprünglichen Projektdateien standen hier nicht mehr als Dateien zur
Verfügung. Die Integration wurde deshalb mit einer ausführbaren Rekonstruktion
der bekannten Kernfunktionen und dem Quelltext des vorherigen Live-Updates
geprüft. Dieser Code wird nur für Tests mitgeliefert, nicht über deine
Anwendung kopiert.

Die Tests decken echte SQLite-Constraints/-Trigger, Cookies, Server-Routen,
Adminrechte, Datei-Löschung und HTTP-Range-Zugriffe ab. Sie ersetzen keinen
Docker-/Cloudflare-Test auf deinem Rechner.

```text
Streamly_Admin_Update/
├── install.py
├── INSTALLIEREN.cmd
├── ADMIN_PASSWORT_AENDERN.cmd
├── payload/app/
│   ├── streamly_admin.py
│   ├── streamly_admin_setup.py
│   ├── streamly_admin_schema.sql
│   ├── static/streamly_admin.css
│   └── templates/
├── tests/
├── pytest.ini
├── requirements-tests.txt
├── TESTBERICHT.md
└── QUELLEN.md
```

Tests lokal aus dem Update-Ordner:

```bash
python -m pip install -r requirements-tests.txt
python -m pytest -q
```

Technische Primärquellen: `QUELLEN.md`.
