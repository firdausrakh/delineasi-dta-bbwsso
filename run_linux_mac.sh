#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "[ERROR] File .env belum ada."
  echo "Salin .env.example menjadi .env lalu pilih DATA_BACKEND=local atau isi credential Cloudflare R2."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/3] Membuat virtual environment..."
  python3 -m venv .venv
  echo "[2/3] Menginstal dependency..."
  . .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi

echo "[3/3] Menjalankan Delineasi DTA BBWS Serayu Opak v1.3.0..."
echo "Buka http://127.0.0.1:8000"
python api/app.py
