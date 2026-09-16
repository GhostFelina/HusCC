#!/usr/bin/env bash
# HusCC kurulumu (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "Python 3.10+ gerekiyor"; exit 1; fi

"$PY" bootstrap.py "$@"
echo
echo "Kisayol icin:  export PATH=\"$(pwd)/.venv/bin:\$PATH\""
