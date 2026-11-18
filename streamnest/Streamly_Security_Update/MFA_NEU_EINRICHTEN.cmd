@echo off
cd /d "%~dp0.."
if exist "compose.live.yaml" goto live
docker compose -f compose.local.yaml exec web python -m app.streamly_security_setup --reset
pause
exit /b
:live
docker compose -f compose.local.yaml -f compose.live.yaml exec web python -m app.streamly_security_setup --reset
pause
