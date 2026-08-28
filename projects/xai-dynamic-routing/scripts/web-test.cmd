@echo off
cd /d "%~dp0.."
python scripts\web_health.py
exit /b %ERRORLEVEL%
