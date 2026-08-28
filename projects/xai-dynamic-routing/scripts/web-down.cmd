@echo off
cd /d "%~dp0.."
where docker >nul 2>&1
if %ERRORLEVEL%==0 (
  docker compose down
  exit /b %ERRORLEVEL%
)
echo No Docker CLI. If the page is running in this window, press Ctrl+C there.
exit /b 0
