@echo off
setlocal
cd /d "%~dp0.."
if not exist "app\main.py" goto wrongfolder
docker info >nul 2>&1
if errorlevel 1 goto nodocker
echo.
echo Streamly: Admin und Moderation installieren.
echo Es gibt KEIN voreingestelltes Admin-Passwort.
echo Gleich kannst du dein eigenes starkes Passwort setzen.
echo.
docker run --rm --mount "type=bind,source=%CD%,target=/project" -w /project python:3.12-slim-bookworm python /project/Streamly_Admin_Update/install.py --project /project
if errorlevel 1 goto failed
if exist "compose.live.yaml" goto live
docker compose -f compose.local.yaml up --build -d
if errorlevel 1 goto failed
docker compose -f compose.local.yaml exec web python -m app.streamly_admin_setup
if errorlevel 1 goto setupfailed
goto done
:live
docker compose -f compose.local.yaml -f compose.live.yaml up --build -d
if errorlevel 1 goto failed
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_admin_setup
if errorlevel 1 goto setupfailed
:done
echo.
echo Admin-Anmeldung: deine bisherige Webseitenadresse mit /admin/login am Ende.
echo Benutzername: admin
echo Nutze das selbst gesetzte oder einmalig angezeigte Passwort.
echo Neue Videos unter /admin pruefen und freigeben.
echo Livestreaming unter /admin/users fuer erlaubte Creator freigeben.
echo Dein Cloudflare-Fenster muss weiterhin offen bleiben.
pause
exit /b 0
:wrongfolder
echo Bitte Streamly_Admin_Update direkt in den vorhandenen streamnest-Projektordner legen.
pause
exit /b 1
:nodocker
echo Bitte Docker Desktop starten und erneut versuchen.
pause
exit /b 1
:setupfailed
echo.
echo Code installiert, Admin-Passwort aber noch nicht eingerichtet oder geaendert.
echo Anleitung fuer die erneute Terminal-Einrichtung: Streamly_Admin_Update\README.md
pause
exit /b 1
:failed
echo.
echo Installation oder Docker-Start fehlgeschlagen. Bitte die Fehlermeldung oberhalb kopieren.
echo Keine Passwoerter, .env-Dateien oder Stream-Schluessel oeffentlich teilen.
pause
exit /b 1
