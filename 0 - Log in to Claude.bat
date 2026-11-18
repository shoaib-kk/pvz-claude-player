@echo off
cd /d "%~dp0"
echo A browser window will open. Sign in with your Claude account.
call claude.cmd auth login
pause
