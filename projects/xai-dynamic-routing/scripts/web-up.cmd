@echo off
REM Avoids PowerShell execution policy. Usage: scripts\web-up.cmd
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" web-up
exit /b %ERRORLEVEL%
