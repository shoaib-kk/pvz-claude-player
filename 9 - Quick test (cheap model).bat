@echo off
cd /d "%~dp0"
rem Player settings: Sonnet at low effort. Plays the current level.
set PVZ_MODEL=sonnet
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py %*
pause
