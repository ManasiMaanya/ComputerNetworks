@echo off
cd /d "%~dp0.."
python scripts\run_tests.py %*
exit /b %ERRORLEVEL%
