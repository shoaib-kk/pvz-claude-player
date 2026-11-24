@echo off
cd /d "%~dp0.."
rem Player settings: Sonnet at low effort.
set PVZ_MODEL=sonnet
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py --campaign --retries 2 %*
pause
