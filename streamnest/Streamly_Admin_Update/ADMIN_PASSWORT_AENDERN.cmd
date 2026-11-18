@echo off
cd /d "%~dp0.."
if exist "compose.live.yaml" goto live
docker compose -f compose.local.yaml exec web python -m app.streamly_admin_setup --reset
pause
exit /b %errorlevel%
:live
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_admin_setup --reset
pause
