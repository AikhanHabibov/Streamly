# Streamly-Sicherheitsupdate: Meldungen und Admin-MFA

**Dieses Paket setzt die zwei zuletzt priorisierten Schritte um:**
1. Melde-System für Videos, Kommentare und Livestreams.
2. Verpflichtende Zwei-Faktor-Anmeldung für den Admin.

Es ergänzt das vorherige **Streamly-Admin-Update**. Das ist keine vollständige
Neuinstallation und kein Nachweis eines bereits öffentlich geprüften Dienstes.
Die Funktionen werden erst nach der Installation auf deinem Rechner aktiv.

**Nicht in diesem Paket:** E-Mail-Bestätigung/Passwort-Reset per E-Mail,
Virenscanner, isolierter Transcoding-Dienst, automatische externe Backups,
dauerhafte Domain/Hosting oder rechtliche Betreibertexte. Diese Punkte bleiben
separate Schritte.

## 1. Vor dem Start

Du brauchst:
- Den bisherigen Projektordner mit installiertem Streamly-Admin-Update.
- Docker Desktop.
- Dein vorhandenes Admin-Passwort.
- Eine Authenticator-App, die zeitbasierte TOTP-Codes unterstützt.
- Einen sicheren Ort für die einmaligen Wiederherstellungscodes.

**Sichere vorher deine Datenbank und Videos.** Die vom Installer automatisch
angelegte Sicherung enthält Projektdateien, nicht deine laufenden Nutzerdaten.

Deine bisherige `PUBLIC_URL`, Benutzerkonten, Videos, Passwörter und Docker-
Volumes werden nicht umbenannt. Den vorhandenen Cloudflare-Tunnel offen lassen.

## 2. Windows: einfacher Installer

### Einzeldatei

1. `Streamly_Sicherheit_Installieren.cmd` herunterladen.
2. Direkt in den bisherigen `streamnest`-Projektordner legen, neben
   `compose.local.yaml`.
3. Docker Desktop öffnen.
4. Die Update-Datei doppelt anklicken.
5. Der Installer sichert Code, erweitert die Anwendung und baut das Docker-Image.
6. Falls noch kein Admin eingerichtet ist, fragt das vorhandene Admin-Setup
   zuerst nach einem starken Passwort. Ein bestehendes Passwort wird dabei
   nicht ersetzt.
7. Danach dein **bestehendes Admin-Passwort** verdeckt im Terminal eingeben.
8. Den QR-Code im Terminal mit deiner Authenticator-App scannen. Alternativ
   den angezeigten Einrichtungsschlüssel manuell eintragen:
   - Name: Streamly / admin
   - Typ: zeitbasiert, TOTP
   - 6 Ziffern, 30 Sekunden
9. Den aktuellen App-Code im Terminal eingeben.
10. Die **zehn einmalig angezeigten Wiederherstellungscodes** sicher speichern.
11. Auf den **nächsten** App-Code warten. Der Einrichtungscode wurde verbraucht.
12. Webseite neu laden und `/admin/login` öffnen.

**Keine QR-Codes, Einrichtungsschlüssel, Passwörter oder Wiederherstellungscodes
als Screenshot oder Support-Log versenden.**

Die CMD-Datei enthält dieses Paket als eingebettete ZIP-Daten. PowerShell
entpackt es lokal und startet `INSTALLIEREN.cmd`. Es wird keine
Ausführungsrichtlinie geändert und keine Firewall-Regel angelegt. Die
Installation verändert nicht deine Cloudflare-Adresse.

### ZIP-Alternative

Den Ordner `Streamly_Security_Update` aus dem ZIP direkt in deinen Projektordner
kopieren und darin `INSTALLIEREN.cmd` doppelt anklicken:

```text
streamnest/
├── app/
│   ├── main.py
│   └── streamly_admin.py
├── compose.local.yaml
├── compose.live.yaml                 # falls das Live-Update vorhanden ist
└── Streamly_Security_Update/
    ├── INSTALLIEREN.cmd
    ├── MFA_NEU_EINRICHTEN.cmd
    ├── install.py
    └── README.md
```

Python muss nicht auf Windows installiert werden. Die Dateianpassung läuft
in einem temporären Python-Container; die MFA-Einrichtung im Web-Container.

Falls dein Quelltext von der erwarteten Version abweicht, bricht der Installer
vor den Dateiänderungen ab. Nicht die Sicherheitsprüfungen aus dem Installer
entfernen. Bei gesperrten Schul-/Arbeitsrechnern die zuständige IT fragen,
nicht bestehende Sicherheitsrichtlinien umgehen.

## 3. Neue Admin-Anmeldung

Die Anmeldung erfolgt ab jetzt in zwei Schritten:

1. `/admin/login`: bisheriges Admin-Passwort.
2. `/admin/mfa`: aktueller App-Code **oder** ein unbenutzter Wiederherstellungscode.

Erst nach dem zweiten Schritt wird eine vollwertige Admin-Sitzung erstellt.
Ein vorhandenes Passwort-only-Cookie reicht auch auf alten Admin-Routen und
für private Medienvorschauen nicht mehr aus.

Die Passwortbestätigung gilt fünf Minuten. Pro Bestätigung sind höchstens fünf
Code-Versuche möglich. Danach musst du wieder mit dem Passwort beginnen.
Zusätzlich greifen die bestehenden Anmelde- und neue MFA-Rate-Limits.

Ein bereits erfolgreich verwendeter App-Code wird nicht erneut akzeptiert.
Warte gegebenenfalls auf den nächsten Code. Smartphone und Computer sollten
automatische, korrekte Uhrzeiten verwenden; die Anzeige deiner lokalen
Zeitzone ist dafür nicht entscheidend.

Unter `/admin/security` siehst du:
- Ob die MFA-Einrichtung aktiv ist.
- Wie viele Wiederherstellungscodes noch unbenutzt sind.
- Ob die aktuelle Sitzung mit einem Wiederherstellungscode bestätigt wurde.

**Kein öffentliches Einrichten, Abschalten oder Zurücksetzen der Admin-MFA.**
Die Einrichtung benötigt Zugriff auf das Server-Terminal und das Admin-Passwort.

Solange die Einrichtung nicht abgeschlossen ist, bleibt der Admin-Zugang
gesperrt. Das ist Absicht; es gibt keinen Passwort-only-Notausgang.

## 4. Wiederherstellung und Gerätewechsel

Jeder Wiederherstellungscode:
- enthält 128 zufällige Bits,
- wird in der Datenbank nur als Hash gespeichert,
- funktioniert nur einmal,
- wird zusätzlich zum Admin-Passwort verwendet.

Du kannst ihn statt des App-Codes auf `/admin/mfa` eingeben. Bindestriche,
Leerzeichen und Gross-/Kleinschreibung werden bei diesen Hex-Codes normalisiert.

Bei Geräteverlust oder zum Erzeugen eines neuen Satzes Codes:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_security_setup --reset
```

Ohne Live-Update den Teil `-f compose.live.yaml` weglassen. Alternativ
`Streamly_Security_Update/MFA_NEU_EINRICHTEN.cmd` öffnen.

Nach Bestätigung des neuen Gerätes werden:
- alle Admin-Sitzungen beendet,
- offene MFA-Anmeldungen gelöscht,
- bisherige Wiederherstellungscodes ungültig,
- der alte Authenticator-Schlüssel ersetzt.

Ein einfacher Admin-Passwort-Reset umgeht MFA nicht. Der neue Login benötigt
weiterhin den zweiten Faktor. Eine noch offene Passwortbestätigung von vor
dem Passwortwechsel kann nicht nachträglich verwendet werden.

TOTP ist kein Passkey und kein umfassender Schutz gegen Phishing oder einen
bereits kompromittierten Browser/Server.

## 5. MFA-Schlüssel und Backups – wichtig

Der TOTP-Einrichtungsschlüssel wird verschlüsselt in SQLite gespeichert.
Der zugehörige Fernet-Schlüssel liegt standardmässig unter:

```text
/data/secrets/admin_mfa.key
```

Im direkten Python-Betrieb entsprechend unter `DATA_DIR/secrets/`.
Bei Docker liegt diese Datei im **Datenvolume**, nicht automatisch in deinem
Windows-Projektordner.

**Datenbank und serverseitige Schlüsseldatei müssen zusammen vertraulich und
verschlüsselt gesichert werden.** Wer beides erlangt, kann den TOTP-Schlüssel
entschlüsseln. Die Verschlüsselung schützt nicht gegen vollständigen Zugriff
auf deinen laufenden Server.

Wenn das bekannte `scripts/backup.py` unverändert erkannt wird, ergänzt der
Installer die Sicherung des Verzeichnisses `secrets`. Bei einem anderen
Backupskript gibt er einen Hinweis aus; dann musst du es selbst prüfen.

Eine vollständige Sicherung des angehaltenen Docker-Datenvolumes enthält
ebenfalls Datenbank, Medien und `secrets`. Backups nicht unverschlüsselt
veröffentlichen und nicht nur auf demselben Rechner aufbewahren.

Optional kann der Betreiber `STREAMLY_MFA_KEY_FILE` auf einen anderen
Schlüsselpfad setzen. Dann ist dieser Pfad **zusätzlich** zu berücksichtigen.
Die Standard-Backup-Erweiterung kann einen beliebigen externen Schlüsselpfad
nicht automatisch erraten.

Fehlt die Schlüsseldatei:
- Ein neuer TOTP-Login schlägt geschlossen fehl.
- Ein gültiger Wiederherstellungscode kann weiterhin zusammen mit dem Passwort
  verwendet werden.
- Danach den Schlüssel aus einem geschützten Backup wiederherstellen oder
  MFA im Server-Terminal vollständig neu einrichten.
- Bestehende gültige MFA-Sitzungen müssen dafür nicht sofort abbrechen.

Dieses Update richtet **keinen automatischen externen Backup-Dienst** ein.
Eine praktische Wiederherstellungsprüfung bleibt notwendig.

## 6. Inhalte melden

Auf Videoseiten, an Kommentaren und auf Live-Seiten erscheint **«Melden»**.

Zum Melden muss man mit einem aktiven normalen Benutzerkonto angemeldet sein.
Eine reine Admin-Anmeldung ist davon getrennt; Admins können direkt moderieren.

Meldende Nutzer wählen:
- eine Kategorie,
- eine Beschreibung mit 10–2000 Zeichen.

Bei Livestreams möglichst den beobachteten Zeitpunkt nennen. Die Meldung
enthält einen kurzen Textauszug und Metadaten, keine automatische Videoaufnahme.

Unter `/reports/mine` sieht man die neuesten 50 Meldungen des eigenen Kontos
und ihren Bearbeitungsstatus. Interne Admin-Notizen und die Meldungen anderer
Nutzer werden dort nicht angezeigt.

Andere normale Nutzer sehen die meldende Person nicht; im Admin-Bereich ist
sie für die Moderation erkennbar. Das System ist **nicht gegenüber dem
Betreiber anonym**.

Beschränkungen:
- Höchstens zehn Einsendungen pro Konto und Stunde.
- Zusätzlich höchstens 60 pro erkannter Client-IP und Stunde.
- Nur eine gleichzeitig offene Meldung desselben Nutzers zum selben
  Inhaltsobjekt. Ein neuer Kommentar mit wiederverwendeter ID gilt nicht
  als dasselbe Objekt.
- Ein inzwischen geänderter Inhalt verlangt vor der Einsendung ein Neuladen
  der Meldeseite.

Bei einem lokalen Tunnel können verschiedene Besucher dieselbe erkannte
Client-IP teilen. Für einen dauerhaften Betrieb muss die vertrauenswürdige
Proxy-Konfiguration geprüft werden; vom Client beliebig gesetzte
Forwarded-Header nicht ungeprüft als echte Identität verwenden.

**Eine Meldung löst keine automatische Sperre oder Löschung aus.**
Eine grosse Anzahl von Meldungen ist kein Beweis für einen Verstoss.

Für Beschwerden ohne Benutzerkonto oder dringende externe Kontaktaufnahme
braucht dein Betrieb zusätzlich einen erreichbaren Kontaktweg. Dieses Paket
ergänzt keine Betreiber-/Kontaktseite.

## 7. Admin-Meldeliste

Unter `/admin/reports` findest du:
- offene Meldungen,
- Fälle in Prüfung,
- bearbeitete Fälle,
- ohne Massnahme geschlossene Fälle.

Einzelfälle enthalten ursprünglichen Textauszug, Meldungsgrund und Verweise
auf das vorhandene Ziel. Vor Entscheidungen Inhalt und Kontext prüfen.

Mögliche Aktionen:
- In Prüfung nehmen.
- Ohne Massnahme schliessen.
- Als bearbeitet markieren.
- Gemeldetes Video dauerhaft löschen.
- Gemeldeten Kommentar löschen.
- Gemeldeten Livestream sperren und Streaming-Rechte entziehen.
- Das ursprüngliche verantwortliche Benutzerkonto sperren.

Destruktive Aktionen haben eine Browser-Bestätigung. Die tatsächlichen
Berechtigungsprüfungen erfolgen trotzdem serverseitig, nicht nur per JavaScript.

Eine Kontosperre entfernt normale Sitzungen, entzieht Streaming-Rechte und
entwertet den Stream-Schlüssel wie im bisherigen Admin-System. Das Beenden
einer bereits bestehenden RTMP-Verbindung bleibt von der Erreichbarkeit der
MediaMTX-API abhängig; die öffentliche Wiedergabe wird unabhängig davon
gesperrt.

Das Melde-System schützt vor Verwechslungen:
- Gelöschte Kommentare können später dieselbe numerische ID erhalten.
- Nach Kontolöschung kann auch eine Benutzer-ID wiederverwendet werden.
- Dafür werden zusätzliche zufällige Inhalts- und Kontokennungen gespeichert.
- Eine alte Meldung darf keinen neuen Kommentar löschen oder eine andere
  Person mit einer wiederverwendeten ID sperren.
- Bei nicht mehr vorhandenem Ziel kann die Meldung ohne weitere Löschung
  abgeschlossen werden.

Moderationsaktionen werden im bestehenden Audit-Protokoll vermerkt.
App-Codes, Wiederherstellungscodes, Passwörter und Sitzungstokens werden dort
nicht protokolliert.

## 8. Datenschutz und Aufbewahrung

Meldungen enthalten Freitext und kurze Inhaltsauszüge. Sie sind für
Administratoren sichtbar, nicht öffentlich. Nach Löschung eines meldenden
Kontos wird dessen Benutzerreferenz entfernt; der Moderationsfall selbst
bleibt zunächst bestehen.

Das ist kein automatisch fertiges Datenschutz-/Beschwerdekonzept:
- Betreiber müssen Kontaktwege, Aufbewahrungsfristen und Löschverfahren festlegen.
- Freitext kann private Daten enthalten.
- Für Meldungen und Audit-Logs gibt es in diesem Update keinen automatischen
  Aufräumdienst.
- Keine Passwörter oder unnötigen privaten Daten in Meldungen schreiben.
- Kein automatischer Inhalts-, Viren- oder Urheberrechtsfilter.

## 9. Was der Installer ändert

- Entfernt den bisherigen Passwort-only-Erfolgspfad der Admin-Anmeldung.
- Ergänzt die zentrale Admin-Sitzungsprüfung um einen bestätigten MFA-Nachweis.
- Ergänzt Tabellen, Routen, Templates, lokale CSS-/JavaScript-Dateien.
- Ergänzt Melde-Links auf den bekannten Video-/Kommentar-/Live-Seiten.
- Ergänzt die bestehenden Admin-Menüs.
- Ergänzt `cryptography`, `qrcode` und einen kompatiblen `cffi`-Versionsbereich
  in den vorhandenen Requirements-Dateien.
- Sichert geänderte Projektdateien unter `streamly-security-backups/`.
- Ändert `.env`, `PUBLIC_URL`, bestehende Benutzerpasswörter oder Volumenamen nicht.

Die zusätzlichen Bibliotheken werden beim Docker-Build heruntergeladen.
Die Anforderungen enthalten kompatible Versionsbereiche, keinen vollständig
neu auditierten, hashgesicherten Dependency-Lock für die ganze Anwendung.
Vor regulärem öffentlichem Betrieb alle Abhängigkeiten auf Sicherheitsupdates
prüfen und das tatsächliche Deployment testen.

Schlüssel, QR-Code und Codes entstehen erst bei der lokalen Terminal-Einrichtung.
Sie sind nicht im Download enthalten.

## 10. Start und Fehlersuche

Mit Live-Update weiterhin:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml up -d
```

Nach Codeänderungen `--build` ergänzen.

Wenn die automatische MFA-Einrichtung abgebrochen wurde:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_security_setup
```

Wenn bereits eine Konfiguration ersetzt werden soll, `--reset` ergänzen.
Ohne Live-Update jeweils `-f compose.live.yaml` weglassen.

Fehler prüfen:

```powershell
docker compose -f compose.local.yaml -f compose.live.yaml ps
docker compose -f compose.local.yaml -f compose.live.yaml logs --tail=60 web
```

Nur Fehlermeldungen teilen. Nicht das Fenster mit QR-Code, geheimem
Einrichtungsschlüssel oder Wiederherstellungscodes senden.

## 11. Prüfung und Grenzen

**43 automatisierte Tests erfolgreich.**

Geprüft wurden unter anderem RFC-6238-Testvektoren, bestehende Passwort-only-
Cookies, parallele TOTP-/Recovery-Anmeldungen, Replay-Schutz, CSRF,
Schlüsselverschlüsselung, Rate-Limits, Meldeberechtigungen und wiederverwendete IDs.

Die aktuellen Originaldateien des Nutzerprojekts waren hier nicht verfügbar.
Die Integration wurde deshalb an einer ausführbaren Rekonstruktion der
bekannten Kern- und Admin-Schnittstellen geprüft. Der Installer akzeptiert
nur die erwarteten Code-Anker.

**Nicht geprüft:** tatsächlicher Windows-Doppelklick, Docker-Build mit den neu
aufgelösten Abhängigkeiten, realer Authenticator-Scan, aktueller Cloudflare-Link,
OBS/MediaMTX-End-to-End oder ein unabhängiges Sicherheitsaudit.

Erfolgreiche Teiltests sind kein Nachweis, dass jede Funktion auf deinem
konkreten öffentlichen Server bereits korrekt läuft.

## 12. Rücknahme

Der Dateibackup-Ordner enthält vorherige Dateien und eine `manifest.json`.
Die Datenbank und die MFA-Schlüsseldatei werden dadurch nicht automatisch
zurückgesichert.

Ein Rollback auf den alten Admin-Code würde wieder Passwort-only-Anmeldungen
ermöglichen. Das nicht unbeabsichtigt öffentlich durchführen. Vor einer
Rücknahme Dienste stoppen und einen konsistenten Stand aus Projektdateien,
Datenbank und Schlüsseln wiederherstellen. Keine ungesicherten Tabellen-
oder Schlüssel-Löschungen im laufenden System vornehmen.

## Dateien für Entwickler

```text
Streamly_Security_Update/
├── install.py
├── INSTALLIEREN.cmd
├── MFA_NEU_EINRICHTEN.cmd
├── payload/app/
│   ├── streamly_security.py
│   ├── streamly_security_setup.py
│   ├── streamly_security_schema.sql
│   ├── templates/
│   └── static/
├── tests/
├── pytest.ini
├── requirements-tests.txt
├── TESTBERICHT.md
└── QUELLEN.md
```

Tests im Update-Ordner:

```bash
python -m pip install -r requirements-tests.txt
python -m pytest -q
```

Primärquellen und Algorithmusreferenzen: `QUELLEN.md`.
