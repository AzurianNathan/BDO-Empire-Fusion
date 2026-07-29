#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/server"
if [ ! -x ".venv/bin/python" ]; then
  echo "Backend is not set up yet. First run:  python3 build.py"
  exit 1
fi
echo "Serving on http://127.0.0.1:8000  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
