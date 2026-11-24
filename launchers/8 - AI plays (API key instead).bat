@echo off
cd /d "%~dp0.."
if "%ANTHROPIC_API_KEY%"=="" (
  echo No API key yet. Run "9 - Set API key (only for 8).bat" first, then open this again.
  pause
  goto :eof
)
".venv\Scripts\python.exe" agent.py --brain claude
pause
