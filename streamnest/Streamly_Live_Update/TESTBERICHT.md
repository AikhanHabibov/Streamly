# Testbericht – Streamly-Live-Update

## Ergebnis

**26 automatisierte Tests bestanden.**

Prüfung in Python 3.13 mit FastAPI, Starlette, HTTPX, pytest und installiertem
FFmpeg. Die Browser-JavaScript-Dateien bestehen zusätzlich `node --check`.

## Geprüft

1. Upload-Initialisierung: Anmeldung, CSRF, Metadaten, Format- und Grössenlimit.
2. Exakte Teilgrössen, unveränderliche gespeicherte Teile, Wiederholungen,
   fehlende Teile und Bereinigung unvollständiger temporärer Dateien.
3. Eigentumsprüfung beim Lesen, Übertragen und Löschen von Uploads.
4. Speicherreservierungen und höchstens drei offene Uploads.
5. Ermittlung bereits gespeicherter Teile und Aktualisierung von Metadaten.
6. Ablauf einer Upload-Sitzung und Entfernung ihrer temporären Dateien.
7. Beschädigte Videodatei: kein veröffentlichtes Video und keine Mediendateireste.
8. Echtes synthetisches H.264-Testvideo: mehrere Teile, Zusammensetzen,
   FFmpeg-Verpackung, Thumbnail und einmalige Veröffentlichung.
9. Unterbrochene Hintergrundverarbeitung: sichtbarer Fehlerstatus.
10. Hashes statt gespeicherter Klartext-Stream-Schlüssel; interne Basic-
    Authentifizierung und Prüfung von Nutzer, Passwort, Pfad und Protokoll.
11. Schlüsselrotation und Deaktivierung: alter Pfad nicht mehr zugreifbar.
12. Live-Seiten aus tatsächlichem, simuliertem MediaMTX-Status und HTML-Escaping.
13. HLS-Proxy: feste interne Zieladresse und begrenzte Asset-Namen.
14. Kontolöschung: Fremdschlüssel-Cascades für neue Datenbanktabellen.
15. Installer: Konfigurationserhalt, Dateibackup und wiederholbarer Lauf.
16. Fremde Projektversion: Abbruch ohne Änderung der Quelldateien.
17. Compose-Konfiguration: RTMP nur an Loopback, HLS/API nur intern.
18. CSRF im Live-Studio und Trennung der Creator-Einstellungen.
19. Fehlendes internes Geheimnis: keine Schlüsselerstellung.
20. Zu wenig freier Datenträger: keine Upload-Reservierung.
21. Ein vollständiger 8-MiB-Teil und ein kurzer letzter Teil.
22. Erneute Kontingentprüfung vor Veröffentlichung, einschliesslich anderer
    offener Reservierungen; Aufräumen bei Überschreitung.
23. Fehlgeschlagener Playerbibliothek-Download: keine Projektdateien geändert.
24. Playerbibliothek: feste Download-Version, Lizenzdatei und lokaler Hash.
    Hierfür wurden Testdaten verwendet, kein echter externer Download.
25. Wiederholtes Finalisieren eines laufenden Jobs startet keinen zweiten Job.
26. MediaMTX-1.21-Statusfelder, Pagination und RTMP-Kick-Endpunkt.

## Was diese Tests nicht behaupten

Die ursprünglichen Projektdateien standen hier nicht als Dateien zur Verfügung.
Die Kernfunktionen wurden durch einen kleinen Testadapter nachgebildet.
Sitzungen, Login und Rate-Limits der ursprünglichen Anwendung wurden in diesem
Lauf nicht erneut vollständig geprüft. Ein nachgebauter Minimalquelltext dient
zur Prüfung des Installers.

MediaMTX-API-Antworten und HLS-Upstream wurden simuliert. Authentifizierungs-
Requests wurden gegen die echten Erweiterungsrouten geprüft, nicht von einem
echten MediaMTX-Prozess gesendet.

Kein Docker-Daemon war verfügbar. Deshalb wurden folgende Punkte nicht
praktisch geprüft:
- Docker-Image-Pull und gemeinsamer Containerstart.
- Die heruntergeladene hls.js-Datei und ihre Ausführung im Live-Browser.
- OBS → RTMP → MediaMTX → HLS → Browser.
- Upload einer vollständigen 2-GiB-Datei.
- Windows-Doppelklick und Dateiübernahme auf dem Nutzerrechner.
- Cloudflare-Tunnel, Bandbreite, Datenschutz- oder Sicherheitseigenschaften
  eines konkreten öffentlichen Deployments.
- Last, Ausfälle unter Echtbedingungen oder ein unabhängiges Sicherheitsaudit.

Dies ist ein implementiertes Erweiterungspaket mit automatisierten Teiltests,
kein Nachweis eines bereits live erprobten Streamingdienstes.
