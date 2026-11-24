@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m pvz.game.controller test
pause
