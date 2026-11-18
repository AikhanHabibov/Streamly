<!-- STREAMLY_SECURITY_README_V1 -->
> **Melde-System und verpflichtende Admin-MFA installiert.** Terminal-Einrichtung zuerst abschliessen.
> Details und Schlüssel-Backup: `Streamly_Security_Update/README.md`.

<!-- STREAMLY_ADMIN_README_V1 -->
> **Admin- und Moderationsupdate aktiv.** Neue/geänderte Videos müssen freigegeben werden; Streaming-Rechte werden separat vergeben.
> Einrichtung und Grenzen: `Streamly_Admin_Update/README.md`. Admin-Anmeldung: `/admin/login`.

<!-- STREAMLY_LIVE_README_V1 -->
> **Streamly-Live-Update installiert.** Die ursprüngliche Anleitung unten beschreibt den alten Stand.
> Neu: Livestreams, Teiluploads bis 2 GiB und 20 GiB Kontospeicher.
> Ab jetzt mit `docker compose -f compose.local.yaml -f compose.live.yaml up -d` starten.
> Details, Grenzen und OBS-Anleitung: `Streamly_Live_Update/README.md`.

# StreamNest

**Eine lauffähige Video-on-Demand-Plattform mit eigenständigem Design.**

Dunkles, responsives Interface mit limettengrünen Akzenten. Echte Konten,
Uploads, Datenbankpersistenz und verbundene Nutzerinteraktionen – kein reines
Frontend-Mockup und kein Nachbau fremder Marken.

## 1. Schnellstart mit Docker – empfohlen

Voraussetzung: Docker mit Compose.

```bash
docker compose -f compose.local.yaml up --build -d
```

Öffne danach **http://127.0.0.1:8000** im Browser und registriere dich.

Optional sechs eigens generierte Demo-Videos anlegen:

```bash
docker compose -f compose.local.yaml exec web python -m app.seed
```

Der Befehl zeigt ein zufällig erzeugtes Passwort für `studio_demo` an.
Es gibt keine fest eingebauten Standard-Zugangsdaten. Die Demovideos enthalten
synthetische Grafik und einen leisen Testton. Ihre Statistiken beginnen bei null.

Beenden:

```bash
docker compose -f compose.local.yaml down
```

Die Daten bleiben im Volume `streamnest_local` erhalten. **Kein `down -v`
verwenden, wenn du die Daten behalten möchtest.**

## 2. Lokal ohne Docker

Voraussetzungen:
- Python 3.11 oder neuer.
- FFmpeg und ffprobe im PATH, einschliesslich H.264-Encoder.
- Für den optionalen Demo-Generator eine Systemschrift, z. B. DejaVu Sans.

### macOS / Linux

FFmpeg zuerst mit dem Paketmanager deines Systems installieren.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m app.seed
python start.py
```

### Windows PowerShell

FFmpeg installieren und `ffmpeg` und `ffprobe` zum PATH hinzufügen.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m app.seed
python start.py
```

Falls das Aktivieren der Umgebung gesperrt ist, kannst du ohne Änderung deiner
PowerShell-Sicherheitsrichtlinie direkt `.venv\Scripts\python.exe` statt `python`
verwenden.

Browseradresse: **http://127.0.0.1:8000**. Der Demo-Schritt ist optional.
Die Installation über pip benötigt Internet; die laufende Anwendung lädt keine
Schriften, Skripte oder Bilder von Drittanbietern nach.

## 3. Was funktioniert?

| Bereich | Umsetzung |
|---|---|
| Startseite | Responsive Videokarten, Kategorien, Sortierung und Seitennavigation |
| Konten | Registrierung, Login per Benutzername/E-Mail, Logout |
| Authentifizierung | Argon2id-Passworthashes, serverseitige Sitzungen, Cookie-Rotation |
| Kanäle | Öffentliche Kanaladresse, Anzeigename, Profiltext, eigener Kanal pro Konto |
| Videos | MP4-/WebM-Upload, Formatprüfung, Metadatenbereinigung, automatisches Vorschaubild |
| Player | HTML5-Player mit Ton, Vollbild und HTTP-Range für das Springen im Video |
| Likes | Ein Like pro Nutzer/Video, erneut klicken zum Entfernen |
| Kommentare | Veröffentlichen; eigene Kommentare löschen; Creator können ihren Kommentarbereich moderieren |
| Abonnements | Kanäle abonnieren/abbestellen und eigener Feed mit abonnierten Inhalten |
| Suche | Videotitel, Beschreibung, Kanal und Kategorie; zusätzlich Kanal-Treffer |
| Statistiken | Aufrufe, Likes, Abonnenten, Videoanzahl und belegter Speicher im Creator Studio |
| Teilen | Öffentlicher permanenter Video-Link, Share-Dialog bzw. Zwischenablage |
| Verwaltung | Videotitel, Beschreibung und Kategorie bearbeiten; Videos löschen |
| Kontosicherheit | Passwort ändern und andere Sitzungen beenden |
| Kontolöschung | Passwortbestätigte Löschung von Konto und eigenen Inhalten aus dem aktiven System |
| Speicherung | SQLite mit WAL-Modus und persistenten Videodateien |
| Betrieb | Docker, Healthcheck, Caddy-Konfiguration für eine öffentliche HTTPS-Domain |

Ein Abonnement bedeutet **einem Kanal folgen**, kein kostenpflichtiges Abo.
Alle veröffentlichten Videos sind öffentlich. Es gibt keine privaten Videos und
keine ausgeblendeten Links als Ersatz für echte Zugriffskontrolle.

### Aufrufe

Ein Aufruf wird nach etwa fünf tatsächlich abgespielten Sekunden erfasst, bei
kürzeren Videos nach etwa 80 Prozent. Pro Konto bzw. anonymer Browsersitzung wird
ein Video höchstens einmal pro UTC-Kalendertag gezählt. Seitenaufrufe allein
erhöhen den Zähler nicht. Das ist eine einfache Engagement-Metrik, **keine
manipulationssichere Reichweitenmessung**; gelöschte Cookies und Bots lassen sich
damit nicht zuverlässig erkennen.

### Upload-Anforderungen

- Standardlimit: 250 MB pro Video, 2048 MB pro Konto.
- MP4 mit H.264; optional AAC-/MP3-Audio.
- WebM mit VP8, VP9 oder AV1; optional Opus-/Vorbis-Audio.
- Höchstens 4 Stunden und 4096 Pixel pro Bilddimension.
- HEVC, MOV und beliebige Handyformate werden nicht automatisch transkodiert.
- Das Vorschaubild entsteht aus einem Frame des Videos.
- Originalname und Browser-MIME-Angabe werden nicht als Sicherheitsnachweis benutzt.
- Dateien erhalten zufällige Namen. Nach erfolgreicher Prüfung wird der Container
  neu geschrieben und Metadaten werden entfernt.
- Browser-/Geräteunterstützung der genannten Codecs kann variieren.
  MP4 mit H.264/AAC ist für dieses MVP der einfachste Austauschweg.

## 4. Projektstruktur

```text
streamnest/
├── app/
│   ├── main.py              # Routen, Sitzungen, Rechteprüfung, Uploads
│   ├── schema.sql           # Tabellen, Constraints, Indizes
│   ├── seed.py              # Optionale synthetische Demo-Inhalte
│   ├── templates/           # Serverseitig gerenderte Seiten und Komponenten
│   └── static/              # CSS, JavaScript und eigenes SVG-Favicon
├── tests/test_platform.py   # Automatisierte Integrations- und Sicherheitstests
├── deploy/Caddyfile         # Reverse Proxy und HTTPS
├── scripts/backup.py        # SQLite-Backup und Kopie der Mediendateien
├── start.py
├── compose.yaml            # Öffentlicher Betrieb
├── compose.local.yaml      # Lokale Docker-Umgebung
├── Dockerfile
├── .env.example
├── requirements.txt        # Versionsbereiche für geplante Updates
├── requirements.lock       # Getestete, fixierte Runtime-Versionen
├── requirements-dev.txt
└── TESTBERICHT.md
```

SQLite-Datenbank und Medien liegen lokal in `data/`, im Container in `/data`.
Die Anwendung legt das initiale Schema beim Start an. Für spätere
Schemaänderungen ist ein versioniertes Migrationsverfahren zu ergänzen.

## 5. Einstellungen

| Variable | Standard | Bedeutung |
|---|---|---|
| `APP_ENV` | development | `production` aktiviert Secure-Cookies und HSTS |
| `PUBLIC_URL` | http://127.0.0.1:8000 | Externe Adresse für Teilen-Links, Origin- und Host-Prüfung |
| `DATA_DIR` | ./data | Datenbank und Videodateien |
| `MAX_VIDEO_MB` | 250 | Dateilimit in MiB |
| `USER_QUOTA_MB` | 2048 | Medienlimit pro Konto in MiB |
| `DEMO_PASSWORD` | zufällig | Optionales Passwort nur beim Demo-Seeding |

Die Anwendung liest im direkten Python-Betrieb keine `.env` automatisch ein.
Diese Datei wird von Docker Compose verwendet. Für einen direkten Start eigene
Umgebungsvariablen in der Shell setzen.

## 6. Öffentlich veröffentlichen

Die Plattform ist hier **nicht bereits online geschaltet**. Du brauchst einen
Server, eine eigene Domain, Zugriff auf DNS sowie Docker Compose.

1. Einen Server mit ausreichend Speicher für Videos bereitstellen.
2. Die gewünschte Subdomain per A-Record und, falls verwendet, AAAA-Record auf
   diesen Server zeigen lassen. Einen nicht erreichbaren AAAA-Record entfernen.
3. Eingehende Ports 80 und 443 freigeben; Port 8000 **nicht** öffentlich freigeben.
4. Projekt auf den Server kopieren und `.env.example` nach `.env` kopieren.
5. In `.env` zum Beispiel `DOMAIN=videos.deine-domain.ch` setzen.
   Nur den Hostnamen angeben, kein Protokoll und keinen Pfad.
6. Starten:

```bash
docker compose up --build -d
docker compose logs -f
```

Caddy ist für Zertifikatsausstellung und HTTPS konfiguriert. Voraussetzung sind
korrektes DNS, erreichbare Ports und eine von der Zertifizierungsstelle
akzeptierte Domain. Die Anwendung ist nur am Domain-Root, nicht unter einem
URL-Unterpfad, vorgesehen.

```bash
docker compose ps
docker compose exec web python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Die produktive Datenbank ist absichtlich getrennt von der lokalen Docker-Demo.
Der Demo-Generator verweigert den Betrieb mit `APP_ENV=production`.

### Reverse-Proxy-Vertrauen

Der produktive Uvicorn-Prozess vertraut Forwarded-Headern, weil nur Caddy über
das interne Compose-Netz auf den Web-Port zugreift. Wenn du das Deployment
änderst und den App-Port direkt erreichbar machst, muss dieses Vertrauen
eingeschränkt werden. Sonst können Angreifer die für Rate-Limits verwendete
Client-IP beeinflussen.

### Vor dem echten öffentlichen Betrieb

- Alle Abhängigkeiten und das Basisimage auf Sicherheitsupdates prüfen;
  `requirements.lock` dokumentiert die hier getesteten Versionen, nicht die
  Garantie, dauerhaft die neuesten Sicherheitsversionen zu enthalten.
- Deployment auf dem tatsächlichen Server testen, inklusive Upload-Grenzen,
  Zertifikat, Speichermangel, Neustart und Wiederherstellung.
- Datenschutzinformationen, Kontakt-/Betreiberangaben und Nutzungsregeln
  passend zum tatsächlichen Betreiber und Einsatz prüfen und ergänzen.
- Verfahren für Meldungen, Moderation und urheberrechtliche Beschwerden
  definieren. Ein globales Moderations-/Admin-Panel ist noch nicht enthalten.
- E-Mail-Verifikation und Wiederherstellung vergessener Passwörter ergänzen,
  bevor du die Registrierung für eine grössere Öffentlichkeit öffnest.
- Monitoring, Speicheralarme, externe Backups und Missbrauchsschutz betreiben.
- Sicherheitsprüfung durchführen lassen. Dieses Projekt ersetzt kein Audit.

## 7. Schutzmassnahmen und Grenzen

Implementiert:
- Argon2id statt Klartextpasswörtern.
- Zufällige Sitzungstokens; in der Datenbank nur deren Hashes.
- HttpOnly-/SameSite-Cookies; in Produktion zusätzlich Secure.
- Siebentägige Sitzungsdauer; Rotation bei An-/Abmeldung.
- CSRF-Token auf allen schreibenden Routen und zusätzliche Origin-Prüfung.
- Anmelde-, Registrierungs-, Kommentar-, Like- und Upload-Rate-Limits.
- Parametrisierte SQL-Abfragen und eindeutige Constraints.
- Automatisches HTML-Escaping, Content Security Policy und weitere Header.
- Eigentumsprüfung bei Änderungen und Löschungen.
- Begrenzte Request-Grösse, Dateiformate, Dateigrösse und Kontospeicher.
- Lokale Medienprüfung mit Zeitlimit; keine vom Nutzer übergebenen Remote-URLs.
- Uploads ausserhalb des statischen Web-Verzeichnisses; keine Ausführung als Code.
- Nicht-Root-Nutzer im App-Container.

Nicht als gelöst darstellen:
- Kein Antiviren-Scan, kein umfassender Schutz vor allen FFmpeg-Schwachstellen.
- Rate-Limits sind einfacher Missbrauchsschutz, kein DDoS-Schutz.
- Kein CAPTCHA, MFA, E-Mail-Versand oder E-Mail-Verifikationsprozess.
- Kein zertifizierter Datenschutz- oder Compliance-Nachweis.
- Nach einem Prozessabbruch können Dateireste übrig bleiben; vor einem
  Bereinigungsjob Datenbank und Mediendateien abgleichen.
- Kontolöschung entfernt keine fremden Kopien öffentlicher Videos und keine
  bereits erstellten Backups. Eine Backup-Aufbewahrungsfrist muss der Betreiber
  festlegen und umsetzen.

## 8. Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Der bereitgestellte Testlauf: **18 Tests erfolgreich**. Details und Grenzen der
Prüfung stehen in `TESTBERICHT.md`. Tests arbeiten in temporären Verzeichnissen
und verändern deine normalen Daten nicht. FFmpeg wird für den echten
Upload-Test benötigt.

## 9. Backups

Datenbank **und** Videos müssen gemeinsam gesichert werden. Für eine konsistente
Kombination muss während der Sicherung der Schreibbetrieb pausiert sein.

Lokale Installation: Webserver beenden, dann zum Beispiel:

```bash
python scripts/backup.py ./data ./backups
```

Docker-Installation, mit pausiertem Webservice:

```bash
docker compose stop web
docker compose run --rm --no-deps --user 0 --entrypoint sh \
  -v "$PWD/backups:/backup" web \
  -c 'mkdir -p /backup && tar -czf /backup/streamnest-backup.tar.gz -C /data .'
docker compose start web
```

Dieser Docker-Befehl ist für eine Unix-Shell. Er überschreibt die genannte
Archivdatei: für mehrere Sicherungsstände einen datierten Dateinamen verwenden.

Backups verschlüsselt an einem anderen Ort aufbewahren. Vor einer
Wiederherstellung den Dienst stoppen, das Archiv in ein leeres Datenvolume
zurückspielen, Eigentümer auf UID 10001 setzen und erst dann neu starten.
Eine Wiederherstellung zuerst auf einem getrennten Testsystem prüfen.

**Achtung:** Eine SQLite-Datei allein reicht nicht aus. Sie enthält die
Videoinformationen, aber nicht die Videodateien.

## 10. Was diese Version bewusst noch nicht ist

Eine Basis für einen kleinen, einzelnen Server – keine Infrastruktur auf
YouTube-/Twitch-Niveau.

Nicht enthalten:
- Livestreaming, Livechat, RTMP oder WebRTC.
- Adaptive HLS-/DASH-Qualitäten und automatische Videotranskodierung.
- Verteilte Upload-Jobs, CDN und S3-/Objektspeicher.
- PostgreSQL, Multi-Server-Betrieb und automatisierte Schemamigrationen.
- Zahlungen, Werbung, kostenpflichtige Mitgliedschaften.
- ML-Empfehlungen oder umfangreiche Analytics-Zeitreihen.
- Globale Administration, Meldequeue, Suchmaschinenoptimierung auf Produktionsniveau.

Medienprüfung läuft innerhalb des Upload-Requests. Bei grösserem Betrieb sollten
diese Aufgaben in isolierte Worker ausgelagert werden. SQLite ist für diese
Single-Server-Version bewusst gewählt; für hohe Schreiblast ist eine
Migration auf PostgreSQL und einen Objektspeicher vorgesehen.

## Technische Referenzen

Die Umsetzung orientiert sich unter anderem an:
- FastAPI: Templates und Request Forms and Files.
- Starlette: FileResponse und HTTP Range Requests.
- OWASP Cheat Sheet Series: Password Storage, Session Management,
  CSRF Prevention und File Upload.

Die genauen Referenzadressen stehen in `QUELLEN.md`.
