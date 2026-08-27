@echo off
setlocal
cd /d "%~dp0"

if not exist .env (
  echo [ERROR] File .env belum ada.
  echo Salin .env.example menjadi .env lalu pilih DATA_BACKEND=local atau isi credential Cloudflare R2.
  exit /b 1
)

if not exist .venv (
  echo [1/3] Membuat virtual environment...
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 exit /b %errorlevel%
  echo [2/3] Menginstal dependency...
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 exit /b %errorlevel%
) else (
  call .venv\Scripts\activate.bat
)

echo [3/3] Menjalankan Delineasi DTA BBWS Serayu Opak v1.0.0.0...
echo Buka http://127.0.0.1:8000
python api\app.py
