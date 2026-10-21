@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
echo Mengunggah bundle runtime termasuk data delineasi, karakteristik DTA, HSS, dan Model Hidrologi...
echo Data model mencakup NetCDF hujan harian, COG hujan tengah bulanan, delapan raster tanah, dan vektor analisis.
%PY% scripts\upload_r2.py
if errorlevel 1 exit /b %errorlevel%
echo.
echo Upload Cloudflare R2 selesai.
