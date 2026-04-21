@echo off
setlocal

cd /d "%~dp0"

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

set QUADLET_MASTER_KEY=1111111111111111111111111111111111111111111111111111111111111111

echo Starting QuadletManager on http://0.0.0.0:8000
uvicorn main:app --host 0.0.0.0 --port 8000
