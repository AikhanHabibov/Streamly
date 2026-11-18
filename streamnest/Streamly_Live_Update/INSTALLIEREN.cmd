@echo off
setlocal
cd /d "%~dp0.."
if not exist "app\main.py" goto wrongfolder
docker info >nul 2>&1
if errorlevel 1 goto nodocker
echo.
echo Streamly: Livestreaming und grosse Uploads installieren
echo Bestehende Projektdateien werden vorher gesichert.
echo Konten und Videos werden nicht geloescht.
echo.
docker run --rm --mount "type=bind,source=%CD%,target=/project" -w /project python:3.12-slim-bookworm python /project/Streamly_Live_Update/install.py --project /project
if errorlevel 1 goto failed
docker compose -f compose.local.yaml -f compose.live.yaml config --quiet
if errorlevel 1 goto failed
docker compose -f compose.local.yaml -f compose.live.yaml up --build -d
if errorlevel 1 goto failed
echo.
echo Update gestartet. Oeffne deine bisherige Webseitenadresse.
echo Neues Studio: /studio/live
echo Livestreams: /live
echo Dein Cloudflare-Fenster muss weiterlaufen.
echo Wenn ein Dienst noch startet, warte kurz und lade die Seite neu.
pause
exit /b 0
:wrongfolder
echo Fehler: Der Ordner Streamly_Live_Update muss direkt in deinem streamnest-Projektordner liegen.
pause
exit /b 1
:nodocker
echo Bitte Docker Desktop starten und danach erneut versuchen.
pause
exit /b 1
:failed
echo.
echo Installation oder Start fehlgeschlagen. Kopiere die Fehlermeldung oberhalb dieser Zeile.
echo Bitte keine .env-Datei und keinen Stream-Schluessel oeffentlich teilen.
pause
exit /b 1
