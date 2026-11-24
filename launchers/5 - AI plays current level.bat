@echo off
cd /d "%~dp0.."
rem Continues whatever level is open, using your Claude login.
rem Player settings: Sonnet at low effort.
set PVZ_MODEL=sonnet
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py %*
pause
