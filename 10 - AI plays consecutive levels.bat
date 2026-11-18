@echo off
cd /d "%~dp0"
set PVZ_MODEL=haiku
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py --campaign --retries 2 %*
pause
