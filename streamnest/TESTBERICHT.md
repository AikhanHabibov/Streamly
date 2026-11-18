# Testbericht

## Automatisierter Lauf

Ergebnis: **18 bestanden**.

Ausgeführt mit Python 3.13, FastAPI 0.128.2, Starlette 0.50.0,
HTTPX 0.28.1 und pytest 9.0.2. FFmpeg war installiert.

Geprüft:
1. Startseite, Sicherheitsheader, Gastberechtigungen, Healthcheck, 404.
2. Registrierung, Login, Logout, Sitzungserneuerung und Argon2id.
3. CSRF-/Origin-Schutz, Passwortlänge und doppelte Registrierung.
4. Likes toggeln, Kommentare schreiben und HTML-Escaping gegen Script-Inhalte.
5. Abonnement-Feed, Abbestellen und Verbot des Selbst-Abonnements.
6. Einmalige Tageszählung und echte HTTP-Range-Antwort für Videodateien.
7. Profil- und Videobearbeitung sowie fremde Zugriffe.
8. Passwortwechsel und Widerruf anderer Sitzungen.
9. Suchfilter und parametrisierte Verarbeitung von SQL-Injection-Eingaben.
10. Zurückweisen einer gefälschten MP4-Datei.
11. Echter H.264-Upload, FFmpeg-Prüfung, Thumbnail, Range-Wiedergabe und Löschung.
12. Request-Grössenlimit und Host-Prüfung.
13. Anmelde-Rate-Limit.
14. Kommentarrechte: fremde Kommentare und Moderation durch den Video-Creator.
15. Passwortbestätigte Kontolöschung mit abhängigen Datensätzen und Videodateien.
16. Ungültiges Unicode-CSRF-Token ergibt 403 statt Serverfehler.
17. Videogrössenlimit mit Bereinigung temporärer Dateien.
18. Kontoquota mit Bereinigung temporärer Dateien.

Zusätzlich wurde der Demo-Generator tatsächlich ausgeführt und hat sechs
gültige Clips mit Vorschaubildern angelegt.

## Darstellung

Startseite mit den gerenderten Original-Templates, CSS, JavaScript und
eingebetteten lokalen Vorschaubildern in Chromium bei Desktopbreite 1440 Pixel
und Mobilbreite 390 Pixel geprüft. Keine JavaScript-Laufzeitfehler; keine
horizontale Seitenüberbreite. Mobiles Menü lässt sich öffnen und mit Escape
schliessen.

Die Browsersitzung verwendete lokal eingebettetes Seiten-HTML, weil direkte
Loopback-Navigation in der Prüfungsumgebung blockiert war. Vollständige
Browser-End-to-End-Tests von Formulareingaben, Mediencodec-Wiedergabe und
Zwischenablage wurden daher nicht durchgeführt; die Backendabläufe wurden mit
FastAPI-TestClient geprüft.

## Nicht ausgeführt

- Kein Docker-Build: in der Prüfungsumgebung war keine Docker-Engine vorhanden.
- Keine Veröffentlichung auf einer echten Domain.
- Kein Test von DNS, TLS-Zertifikatsausstellung oder externer Erreichbarkeit.
- Kein Lasttest, Penetrationstest oder unabhängiges Sicherheitsaudit.
- Kein Test aller Browser, Betriebssysteme und Videocodecs.
- Kein praktischer Wiederherstellungstest der Docker-Backup-Anleitung.

Die erfolgreiche lokale Prüfung ist kein Nachweis eines bereits
produktiv erprobten oder vollständig abgesicherten Internetdienstes.
