# Streamly: Livestreaming und grosse Uploads

**Update für die bereits bereitgestellte StreamNest/Streamly-FastAPI-Anwendung.**
Keine komplette Neuinstallation, keine neue Marke und kein Ersatz für deinen
Projektordner. Bestehende Datenbanknamen, Docker-Volumes, Benutzerkonten und
veröffentlichte Videos werden nicht umbenannt oder gelöscht.

Das Paket ist Quellcode mit automatisierter Anpassung der bekannten
Projektversion. Es ist **noch nicht auf deinem Rechner installiert**.

## 1. Einfache Installation unter Windows

Voraussetzung: Dein bisheriges Projekt funktioniert mit Docker Desktop.

### Variante A: einzelne Update-Datei

Falls du `Streamly_Update_Installieren.cmd` heruntergeladen hast:

1. Lege diese Datei direkt in deinen bisherigen `streamnest`-Projektordner.
   Neben der Datei müssen `compose.local.yaml` und der Ordner `app` liegen.
2. Docker Desktop starten.
3. Doppelklick auf `Streamly_Update_Installieren.cmd`.
4. Das Fenster zeigt Download, Sicherung, Installation und Docker-Neustart.
   Bei einer Fehlermeldung nicht weiterprobieren, sondern die Meldung kopieren.
   Keine Geheimnisse aus `.env` oder OBS öffentlich teilen.
5. Öffne deine bisherige Webseitenadresse und lade mit **Ctrl + F5** neu.

Die einzelne CMD-Datei enthält dieses ZIP als Base64-Daten. PowerShell entpackt
es lokal nach `Streamly_Live_Update`; danach wird der unten beschriebene,
offen einsehbare Installer gestartet. Es wird keine PowerShell-Ausführungsrichtlinie
geändert und keine Firewall-Regel angelegt.

### Variante B: ZIP

1. Entpacke das ZIP.
2. Kopiere den Ordner `Streamly_Live_Update` in deinen vorhandenen Projektordner.

Die Struktur muss danach so aussehen:

```text
streamnest/
├── app/
├── Dockerfile
├── compose.local.yaml
└── Streamly_Live_Update/
    ├── INSTALLIEREN.cmd
    ├── install.py
    ├── payload/
    └── README.md
```

3. Docker Desktop starten.
4. `Streamly_Live_Update/INSTALLIEREN.cmd` doppelt anklicken.
5. Danach die bisherige Webseite öffnen und mit **Ctrl + F5** aktualisieren.

### Was der Installer tut

- Prüft, ob die erwartete FastAPI-Projektversion vorliegt. Bei abweichendem
  Quelltext bricht er vor Änderungen ab.
- Lädt hls.js 1.7.4 mit Lizenz über HTTPS herunter und legt es als lokale
  statische Datei ab. Zuschauer müssen dafür später keinen externen CDN-Code laden.
  Ein lokaler SHA-256-Wert dokumentiert den Download; dies ist kein Ersatz für
  einen unabhängig geprüften Lieferketten-Lock.
- Sichert die zu ändernden Dateien in `streamly-update-backups/`.
- Fügt Live-Routen, Upload-Routen, Templates, JavaScript und CSS hinzu.
- Ergänzt das SQLite-Schema um neue Tabellen; die bisherige Anwendung legt diese
  beim nächsten Start an. Bestehende Tabellen werden nicht gelöscht.
- Ergänzt in `.env` ein zufälliges `STREAMLY_INTERNAL_SECRET`.
  Andere vorhandene Einstellungen bleiben erhalten.
- Ergänzt interne Host-, Request-Limit- und Cache-Regeln.
- Behält Cookie-Namen, Datenbankpfad, Medienpfad und Volume-Namen unverändert.
- Startet Docker mit der zusätzlichen Datei `compose.live.yaml`.

Das Dateibackup ist **kein Backup deiner Datenbank und Videodateien**. Sichere
vor grösseren Änderungen auch deine Daten wie in der ursprünglichen README.

Das Update benötigt Internet für das Python-Image, die MediaMTX-Containerdatei
und den einmaligen Download der Playerbibliothek. Python muss nicht auf Windows
installiert sein; der Installer läuft in einem temporären Python-Container.

Wenn der Windows-Installer in einer verwalteten Schul-/Arbeitsumgebung blockiert
wird, nicht Sicherheitsrichtlinien umgehen: bitte die zuständige IT fragen.

## 2. Neue Funktionen

### Livestreaming

- `/studio/live`: Titel, Beschreibung, Kategorie und OBS-Verbindung.
- Pro Konto ein eigener Streaming-Kanal.
- Einmalig angezeigte, zufällige Stream-Schlüssel; gespeichert wird nur ihr Hash.
- Schlüssel neu erstellen oder Streaming deaktivieren.
- `/live`: tatsächlich sendende Creator, ermittelt über die MediaMTX-API.
- `/live/benutzername`: öffentliche Wiedergabeseite mit HLS-Player.
- Regelmässige Statusabfrage; Offline-Anzeige statt erfundener Live-Badges.
- Wiedergabe über dieselbe öffentliche Webadresse; interne HLS- und API-Ports
  werden nicht direkt im Internet veröffentlicht.
- Live-Wiedergabe mit Safari-HLS oder hls.js/Media Source Extensions, soweit
  der Browser und die Codecs dies unterstützen.

### Grössere Video-Uploads

- Standard: **2 GiB pro Video**, **20 GiB pro Benutzerkonto**.
- Übertragung in **8-MiB-Teilen** statt einem einzigen riesigen Request.
- Vollständige Teile werden auf dem Server gespeichert.
- Vorübergehende Fehler werden pro Teil bis zu dreimal versucht.
- Fortsetzen nach Seitenneuladen oder Verbindungsabbruch im selben Browser:
  erneut anmelden, dieselbe Originaldatei wählen und erneut veröffentlichen.
- Die Zuordnung im Browser verwendet localStorage und Dateiname, Dateigrösse
  und Änderungszeit. Ohne zugelassenen Browser-Speicher ist diese automatische
  Wiedererkennung nicht verfügbar.
- Vorhandene Teile können bis 24 Stunden nach der letzten Aktivität
  wiederverwendet werden. Abgelaufene Sitzungen werden abgewiesen.
- Es gibt maximal drei offene Uploads pro Konto.
- Nach dem Übertragen werden Teile zusammengesetzt, das Video durch die
  vorhandene FFmpeg-Verarbeitung geprüft und ein Thumbnail erzeugt.
- Die Verarbeitung erfolgt nach einer kurzen Startantwort im Hintergrund;
  die Seite fragt den Status ab.
- Reservierungen und endgültige Dateigrösse werden gegen das Kontolimit geprüft.
- Zugehörigkeit und CSRF-Prüfung gelten auch für Teilübertragungen.

**Unverändert:** MP4/H.264 bzw. die bisher unterstützten WebM-Codecs,
maximal 4 Stunden und maximal 4096 Pixel je Bilddimension.
Dies ist kein allgemeiner HEVC-/MOV-Konverter. Die Anwendung erstellt keine
Videoschnitt-Projekte; sie veröffentlicht fertige Dateien.

## 3. Mit OBS live gehen

OBS offiziell installieren: https://obsproject.com/
Windows-Anleitung: https://obsproject.com/kb/windows-installation

1. Auf Streamly anmelden.
2. In der Navigation **Livestream Studio** öffnen.
3. Titel, Kategorie und Beschreibung speichern.
4. **Stream-Schlüssel erstellen** anklicken.
5. Server und einmalig angezeigten Schlüssel nach OBS kopieren.
6. In OBS unter Einstellungen → Stream:
   - Dienst: **Benutzerdefiniert**
   - Server: wie im Streamly-Studio angezeigt, lokal normalerweise
     `rtmp://127.0.0.1:1935`
   - Stream-Schlüssel: den **gesamten** Wert aus Streamly kopieren,
     einschliesslich `?user=...&pass=...`
7. Für diese Konfiguration H.264 für Video und AAC für Audio benutzen.
   Ein Keyframe-Intervall von 2 Sekunden ist ein sinnvoller Startwert.
8. Quelle für Bildschirm/Kamera/Spiel und die Audiogeräte auswählen.
9. In OBS **Streaming starten**.
10. Auf Streamly die öffentliche Live-Seite öffnen. Browser können den Ton
    zunächst stummschalten; die Lautstärke im Player einschalten.

HLS arbeitet mit Segmenten und hat eine Verzögerung. Das Paket bietet keinen
verzögerungsfreien Videochat. Wenn der Stream gerade erst startet, können Player
und Statusanzeige einen Moment brauchen.

**Schlüssel geheim halten:** Nicht in Screenshots, Chats oder Logs teilen.
Bei Verlust neu erstellen. Vor einem Schlüsselwechsel den Stream in OBS stoppen.
Die Erweiterung versucht zusätzlich, eine vorhandene RTMP-Verbindung über die
MediaMTX-API zu beenden; das hängt von der Erreichbarkeit dieses Dienstes ab.

### Wo OBS laufen kann

Die mitgelieferte Konfiguration veröffentlicht RTMP nur auf
**127.0.0.1:1935**. OBS muss deshalb auf demselben Computer wie Docker laufen.

Für einen entfernten, eigenen Server kannst du den RTMP-Port mit einem
authentifizierten SSH-Tunnel zu deinem Rechner weiterleiten, zum Beispiel:

```powershell
ssh -L 1935:127.0.0.1:1935 benutzer@dein-server
```

Der Server benötigt dafür SSH-Zugang und einen laufenden MediaMTX-Dienst.
Der lokale Port muss frei sein. In OBS bleibt die Adresse dann
`rtmp://127.0.0.1:1935`. Diese Variante ist für berechtigte Betreiber, nicht für
eine frei registrierbare Öffentlichkeit.

**Für beliebige entfernte Creator ist ein zusätzlicher öffentlicher,
abgesicherter RTMPS-Eingang mit gültigem Zertifikat nötig.** Das ist in diesem
lokalen Update nicht automatisch eingerichtet. Den unverschlüsselten RTMP-Port
1935 nicht einfach im Router oder am Server für das Internet freigeben.

## 4. Öffentliche Webseite und Cloudflare

Dein bisheriger HTTPS-Testlink kann grundsätzlich den Webzugang und die
segmentierten HTTP-Anfragen erreichen, sofern Tunnel und Proxy diese Anfragen
zulassen. `PUBLIC_URL` muss weiterhin die tatsächliche öffentliche Adresse
enthalten; `APP_ENV: production` bleibt bei öffentlichem HTTPS-Zugriff gesetzt.

**Das Update ändert deine bisherige PUBLIC_URL nicht.**

- Der Tunnel und dein PC müssen weiterlaufen.
- Ein neuer Quick Tunnel erzeugt eine neue Adresse.
- Quick Tunnels haben unter anderem ein Limit gleichzeitiger Anfragen und
  sind keine zugesicherte Produktionsplattform.
- Teiluploads sind normale kleine Requests. Sie sind keine Zusage, dass ein
  bestimmter Proxy unbegrenzte Dateimengen oder Bandbreite erlaubt.
- Cloudflare-Regeln und Vertragsbedingungen für Video- und grosse Dateiinhalte
  sind unabhängig von der technischen Chunk-Grösse einzuhalten.
- Für regulären öffentlichen Videobetrieb einen passenden eigenen Server oder
  einen ausdrücklich dafür vorgesehenen Mediendienst verwenden.

Eine temporäre Testadresse ersetzt keinen dauerhaft eingerichteten Streaming-
Server, kein CDN und keinen Schutz gegen grosse Zuschauerzahlen.

## 5. Ab jetzt richtig starten

Immer **beide** Compose-Dateien angeben:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml up -d
```

Nach Änderungen am Code:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml up --build -d
```

Status:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml ps
```

Logs:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml logs --tail=80 web mediamtx
```

Stoppen:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml down
```

**Nicht `down -v` verwenden**, wenn Daten erhalten bleiben sollen.
Dein separates Cloudflare-Terminal wird von diesen Befehlen nicht beendet.

Im Paket liegt dafür zusätzlich `STARTEN.cmd`.

### Eigene öffentliche Domain

Für die ursprüngliche Serverkonfiguration stattdessen:

```bash
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

Voraussetzungen sind weiterhin deine korrekt konfigurierte Domain, `.env`,
Caddy/HTTPS und ausreichend Serverspeicher. RTMP bleibt absichtlich nur lokal
gebunden. Die öffentliche Creator-Einspeisung wird dadurch nicht automatisch
eingerichtet.

## 6. Speicher und Betriebsgrenzen

- Ein Upload benötigt zeitweise Originalteile, zusammengesetzte Datei,
  veröffentlichte Datei und Thumbnail: ungefähr die dreifache Videogrösse
  plus Reserve einplanen.
- Der Init-Endpunkt prüft den freien Speicher konservativ. Trotzdem kann bei
  gleichzeitigen Uploads oder fremden Prozessen später Speichermangel entstehen.
- Abgelaufene Upload-Dateien werden bei späteren Upload-Initialisierungen
  bereinigt, bzw. beim Zugriff auf eine abgelaufene Sitzung. Ohne weitere
  Aktivität können Dateireste länger als 24 Stunden auf dem Datenträger liegen.
  Ein regelmässiger Wartungsjob ist für den produktiven Betrieb zu ergänzen.
- Nach Kontolöschung können unvollständige Upload-Verzeichnisse bis zu einer
  solchen Bereinigung übrig bleiben; sie sind nicht öffentlich abrufbar.
- Teilübertragung ist unterbrechbar. Die anschliessende FFmpeg-Verarbeitung ist
  **kein dauerhaft gespeicherter Job-Queue-Prozess**: beendet sich der Worker,
  kann dieser Schritt fehlschlagen und muss neu gestartet werden.
- Ein veralteter Verarbeitungsstatus wird nach 30 Minuten als Fehler markiert.
  Fertige Videos werden nicht doppelt veröffentlicht.
- Gleichzeitige Streams brauchen Upload-Bandbreite, CPU und Speicher. Die
  mitgelieferten Containerlimits sind eine kleine Testkonfiguration, kein
  Lastprofil für eine grosse Streamingplattform.
- MediaMTX remuxt Protokolle, passt aber in diesem Paket nicht automatisch
  Bitrate oder Codec an.

## 7. Noch nicht enthalten

- Livechat und Chatmoderation.
- Automatische Übernahme einer Live-Aufzeichnung als Video.
- Aufzeichnung auf dem Server: `record: false` ist bewusst gesetzt, damit nicht
  unkontrolliert der Datenträger gefüllt wird.
- Aufnahme direkt im Browser oder Senden vom Smartphone ohne Zusatzsoftware.
- Mehrere Qualitätsstufen oder adaptives Transcoding.
- Manipulationssichere Zuschauerstatistiken.
- Frei zugänglicher öffentlicher RTMPS-Ingest samt Zertifikatsverwaltung.
- Skalierung auf mehrere Server oder eine zuverlässige externe Job-Queue.

Wenn du einen Stream später als Video anbieten möchtest, nimm ihn parallel in
OBS auf, exportiere bei Bedarf in ein unterstütztes Format und lade die Datei
anschliessend über Streamly hoch.

## 8. Tests und Transparenz

**26 automatisierte Tests bestanden.** Der genaue Umfang steht in
`TESTBERICHT.md`. Es wurden echte FFmpeg-Dateien in Teilen übertragen,
zusammengesetzt, neu verpackt und mit Thumbnail gespeichert.

Wichtig: Die Original-Projektdateien und eine Docker-Engine waren in dieser
Bearbeitungsumgebung nicht verfügbar. Die Routen wurden deshalb mit einem
minimalen Adapter für die bekannten Kernfunktionen getestet. Installation und
Kompatibilität wurden an nachgebildeten Quelltext-Ankern geprüft.

**Nicht durchgeführt:** echter Docker-Start, OBS→RTMP→HLS-End-to-End-Test,
Cloudflare-Durchsatztest oder ein kompletter 2-GiB-Upload.

Die Tests beweisen die geprüften Teilabläufe, nicht einen bereits erprobten
Produktivbetrieb auf deinem Rechner. Der Installer prüft deshalb die erwarteten
Code-Stellen und legt ein Backup an.

## 9. Rückgängig machen

- Dienste mit beiden Compose-Dateien stoppen.
- Unter `streamly-update-backups/<Zeitstempel>/files` liegen vorherige Dateien.
- Diese an ihre ursprünglichen Stellen zurückkopieren.
- Neu hinzugefügte Dateien stehen mit `existed: false` in `manifest.json`.
  Bei Bedarf gezielt entfernen.
- Danach mit der ursprünglichen `compose.local.yaml` neu bauen und starten.

Die neuen SQLite-Tabellen können bestehen bleiben; sie werden von der alten
Anwendung nicht verwendet. Nicht ohne vollständige Datensicherung an der
Datenbank manipulieren. Die Backup-Ordner können alte `.env`-Dateien enthalten:
vertraulich aufbewahren.

## 10. Inhalt für Entwickler

```text
Streamly_Live_Update/
├── install.py
├── INSTALLIEREN.cmd
├── STARTEN.cmd
├── payload/
│   ├── compose.live.yaml
│   ├── streamly-live/mediamtx.yml
│   └── app/
│       ├── streamly_extension.py
│       ├── streamly_schema.sql
│       ├── templates/
│       └── static/
├── tests/
├── pytest.ini
├── requirements-tests.txt
├── TESTBERICHT.md
└── QUELLEN.md
```

Der Installer kopiert `payload` ins vorhandene Projekt, ergänzt den Router am
Ende von `app/main.py` und erweitert das bestehende initiale SQL-Schema.
Er ersetzt **nicht** die komplette Hauptanwendung.

Die Testumgebung installieren und aus dem Update-Ordner starten:

```bash
python -m pip install -r requirements-tests.txt
python -m pytest -q
```

Die vorhandene Anwendung braucht keine zusätzlichen Python-Pakete. Der neue
Router verwendet FastAPI/Starlette und die Python-Standardbibliothek. MediaMTX
ist ein separater Container; hls.js wird beim Installieren lokal gespeichert.

Technische Primärquellen: siehe `QUELLEN.md`.
