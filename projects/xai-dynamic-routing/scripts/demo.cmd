@echo off
cd /d "%~dp0.."
python scripts\demo.py %*
exit /b %ERRORLEVEL%
