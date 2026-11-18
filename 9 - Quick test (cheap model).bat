@echo off
cd /d "%~dp0"
rem Cheapest/fastest settings for testing: Haiku at low effort. Plays the current level.
set PVZ_MODEL=haiku
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py %*
pause
