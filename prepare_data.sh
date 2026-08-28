#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
if [[ ! -x "$PY" ]]; then
  echo "Virtual environment belum ada. Jalankan run_linux_mac.sh sekali terlebih dahulu."
  exit 1
fi
"$PY" scripts/prepare_hydro_data.py
