@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Parando NotasFlow...
docker compose down
echo Pronto.
pause
