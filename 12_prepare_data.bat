@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo  PREPARE DATASET HIDROLOGI - DELINEASI DTA
ECHO ================================================

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment belum ada. Menjalankan run.bat sekali akan membuatnya.
  echo Atau buat manual: py -m venv .venv
  pause
  exit /b 1
)

".venv\Scripts\python.exe" scripts\prepare_hydro_data.py
if errorlevel 1 (
  echo.
  echo PREPARE GAGAL. Dataset runtime lama tidak diubah.
  pause
  exit /b 1
)

echo.
echo PREPARE SELESAI. Pastikan data\shared berisi dem.tif, plen.tif, landcover.tif, cn2.tif, streams_analysis.zip, dan landsystem.zip sebelum ekspor R2.
pause
