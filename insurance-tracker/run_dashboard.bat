@echo off
REM Policy Tracker dashboard - local only (http://127.0.0.1:8050)
cd /d "%~dp0"
set PYTHONUTF8=1
echo Starting PostgreSQL (Docker in WSL)...
wsl --cd "%~dp0" docker compose up -d
start "" http://127.0.0.1:8050/
.venv\Scripts\python.exe dashboard\server.py --port 8050
