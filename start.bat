@echo off
setlocal

cd /d "%~dp0"

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    REM requirements.in, not the requirements.txt lock: that lock is compiled on
    REM Linux, so it pins uvloop and httptools with no environment markers and
    REM no Windows wheel exists for them. Windows dev runs resolve from the
    REM ranges instead and let pip apply each package's own platform markers.
    pip install -r requirements.in
) else (
    call venv\Scripts\activate.bat
)

echo Installing/updating frontend vendor assets...
npm ci

set QUADLET_MASTER_KEY=1111111111111111111111111111111111111111111111111111111111111111

echo Starting QuadletManager on http://0.0.0.0:8000
uvicorn main:app --host 0.0.0.0 --port 8000
