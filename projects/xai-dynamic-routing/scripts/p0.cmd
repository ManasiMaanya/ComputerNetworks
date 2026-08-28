@echo off
cd /d "%~dp0.."
python scripts\load_sample.py
exit /b %ERRORLEVEL%
