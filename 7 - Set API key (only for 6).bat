@echo off
echo Paste your Anthropic API key (from console.anthropic.com) and press Enter.
echo It is saved to your Windows user environment, not to this folder.
set /p KEY="Key: "
setx ANTHROPIC_API_KEY "%KEY%" >nul
echo Saved. Close this window; new windows will have the key.
pause
