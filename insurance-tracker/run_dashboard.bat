@echo off
REM Policy Tracker dashboard - local only (http://127.0.0.1:8050)
cd /d "%~dp0"
set PYTHONUTF8=1
start "" http://127.0.0.1:8050/
.venv\Scripts\python.exe dashboard\server.py --port 8050
