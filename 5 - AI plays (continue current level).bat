@echo off
cd /d "%~dp0"
rem Uses your Claude subscription through Claude Code (log in once with: claude auth login)
".venv\Scripts\python.exe" agent.py --brain subscription
pause
