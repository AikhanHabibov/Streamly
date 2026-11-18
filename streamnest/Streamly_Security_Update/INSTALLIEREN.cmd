@echo off
setlocal
cd /d "%~dp0.."
if not exist "app\streamly_admin.py" goto noadmin
docker info >nul 2>&1
if errorlevel 1 goto nodocker
echo.
echo Streamly: Melde-System und verpflichtende Admin-Zwei-Faktor-Anmeldung.
echo Halte dein bestehendes Admin-Passwort und eine Authenticator-App bereit.
echo Bestehende Admin-Sitzungen ohne zweiten Faktor werden nicht mehr akzeptiert.
echo.
docker run --rm --mount "type=bind,source=%CD%,target=/project" -w /project python:3.12-slim-bookworm python /project/Streamly_Security_Update/install.py --project /project
if errorlevel 1 goto failed
if exist "compose.live.yaml" goto live
docker compose -f compose.local.yaml up --build -d
if errorlevel 1 goto failed
docker compose -f compose.local.yaml exec web python -m app.streamly_admin_setup
if errorlevel 1 goto setupfailed
docker compose -f compose.local.yaml exec web python -m app.streamly_security_setup
if errorlevel 1 goto setupfailed
goto done
:live
docker compose -f compose.local.yaml -f compose.live.yaml up --build -d
if errorlevel 1 goto failed
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_admin_setup
if errorlevel 1 goto setupfailed
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_security_setup
if errorlevel 1 goto setupfailed
:done
echo.
echo Einrichtung abgeschlossen. Einmalig angezeigte Wiederherstellungscodes sicher speichern.
echo WARTE auf den naechsten App-Code, dann auf deiner Webseite /admin/login oeffnen.
echo Meldungen: /admin/reports  -  Sicherheitsstatus: /admin/security
echo Cloudflare-Fenster weiterhin offen lassen.
pause
exit /b 0
:noadmin
echo Das vorherige Streamly-Admin-Update fehlt.
echo Dieses Paket muss neben compose.local.yaml im vorhandenen streamnest-Projekt liegen.
echo Keine Dateien geaendert.
pause
exit /b 1
:nodocker
echo Bitte Docker Desktop starten.
pause
exit /b 1
:setupfailed
echo.
echo Code installiert, Zwei-Faktor-Einrichtung aber nicht vollstaendig abgeschlossen.
echo Admin-Zugriff ist bis dahin gesperrt. Anleitung: Streamly_Security_Update\README.md
echo Keine QR-Codes, Passwoerter oder Wiederherstellungscodes an den Support senden.
pause
exit /b 1
:failed
echo Installation oder Docker-Start fehlgeschlagen. Bitte nur die Fehlermeldung teilen.
pause
exit /b 1
