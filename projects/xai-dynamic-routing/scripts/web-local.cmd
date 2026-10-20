@echo off
REM Start the web demo without Docker (needs the project venv). Open http://127.0.0.1:8765/ ; stop with Ctrl+C.
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m uvicorn web.app:app --host 127.0.0.1 --port 8765
exit /b %ERRORLEVEL%
