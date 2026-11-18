@echo off
cd /d "%~dp0.."
docker compose -f compose.local.yaml -f compose.live.yaml up -d
pause
