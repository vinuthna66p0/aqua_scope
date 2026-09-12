#!/usr/bin/env bash
# Convenience launcher for the Oil Spill Intelligence & Decision Support System prototype.
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Installing dependencies..."
./venv/bin/pip install -q -r requirements.txt

echo "Starting server at http://localhost:8000 ..."
cd backend
../venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000