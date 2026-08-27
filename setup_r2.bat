@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Membuat virtual environment...
  python -m venv .venv || exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo .env dibuat dari .env.example.
  echo Isi LOCAL_DATA_DIR bila data tidak berada di folder repo\data.
  echo Isi credential Cloudflare R2 sebelum upload.
) else (
  echo .env sudah tersedia; tidak ditimpa.
)
echo.
echo Setup R2 selesai. Tidak ada credential Supabase yang diperlukan.
