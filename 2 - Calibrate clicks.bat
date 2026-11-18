@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" controller.py calibrate
pause
