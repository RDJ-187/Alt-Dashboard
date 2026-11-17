@echo off
REM Full local-LLM cross-check (resumable). Safe to close and re-run: finished files are cached.
cd /d "%~dp0"
set PYTHONUTF8=1
echo [%date% %time%] LLM run started >> data\llm_run.log
.venv\Scripts\python.exe -W ignore run_pipeline.py --root "..\OneDrive_2026-11-14\HR Assignment" --llm >> data\llm_run.log 2>&1
echo [%date% %time%] LLM run finished >> data\llm_run.log
.venv\Scripts\python.exe -W ignore tools\export_excel.py >> data\llm_run.log 2>&1
