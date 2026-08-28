@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment belum ada. Jalankan run.bat sekali terlebih dahulu.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\benchmark_datasets.py
pause
