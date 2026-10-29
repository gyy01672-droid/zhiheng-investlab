@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\update_data.py --train --refresh-universe
pause
