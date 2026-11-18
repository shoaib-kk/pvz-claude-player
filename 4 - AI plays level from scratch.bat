@echo off
cd /d "%~dp0"
rem Restarts the current level, lets Claude pick plants, and plays it to the end.
".venv\Scripts\python.exe" agent.py --restart
pause
