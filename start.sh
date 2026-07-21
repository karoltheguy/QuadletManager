#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing/updating dependencies..."
pip install -r requirements.txt

echo "Installing/updating frontend vendor assets..."
npm ci

export QUADLET_MASTER_KEY=1111111111111111111111111111111111111111111111111111111111111111

echo "Starting QuadletManager on http://0.0.0.0:8000"
uvicorn main:app --host 0.0.0.0 --port 8000