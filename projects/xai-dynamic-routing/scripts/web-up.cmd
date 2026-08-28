@echo off
REM Run from anywhere. In PowerShell use:  .\scripts\web-up.cmd
cd /d "%~dp0.."

where docker >nul 2>&1
if %ERRORLEVEL%==0 (
  echo Using Docker Compose...
  docker compose up --build -d
  if errorlevel 1 exit /b 1
  echo Open http://127.0.0.1:8765/
  echo Then: .\scripts\web-test.cmd
  exit /b 0
)

echo Docker CLI not found on Windows PATH.
echo Starting local uvicorn on 127.0.0.1:8765  (Ctrl+C to stop)
echo Install Docker Desktop + WSL integration later: docs\web\backend-docker.md
python -m uvicorn web.app:app --host 127.0.0.1 --port 8765
exit /b %ERRORLEVEL%
