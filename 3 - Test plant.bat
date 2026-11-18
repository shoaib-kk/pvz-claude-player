@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" controller.py test
pause
