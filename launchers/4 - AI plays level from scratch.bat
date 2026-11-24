@echo off
cd /d "%~dp0.."
rem Restarts the current level, lets Claude pick plants, and plays it to the end.
rem Player settings: Sonnet at low effort.
set PVZ_MODEL=sonnet
set PVZ_EFFORT=low
".venv\Scripts\python.exe" agent.py --restart %*
pause
