@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
if not exist "data\shared\daily_rainfall_gridded_0.02.nc" if not exist "data\shared\semimonthly_rainfall_gridded_0.02.nc" (
    echo ERROR: NetCDF hujan harian atau tengah bulanan tidak ditemukan di data\shared.
    exit /b 1
)
echo Memeriksa data hujan dan menyiapkan COG serta laporan 30 nilai tertinggi...
if exist "data\shared\daily_rainfall_gridded_0.02.nc" (
    "%PY%" scripts\prepare_daily_rainfall.py "data\shared\daily_rainfall_gridded_0.02.nc" --output "data\shared\rainfall.tif" --report-dir "data\shared\rainfall_review"
) else (
    "%PY%" scripts\prepare_rainfall.py "data\shared\semimonthly_rainfall_gridded_0.02.nc" --output "data\shared\rainfall.tif" --report-dir "data\shared\rainfall_review"
)
if errorlevel 1 exit /b %errorlevel%
echo.
echo Memeriksa dan membundel data delineasi, karakteristik DTA, HSS, dan Model Hidrologi untuk runtime R2...
echo Model Hidrologi menyertakan hujan harian, COG hujan tengah bulanan, delapan raster tanah, dan vektor analisis.
"%PY%" scripts\export_local_to_r2.py --overwrite
if errorlevel 1 exit /b %errorlevel%
echo.
echo Bundle R2 termasuk data Model Hidrologi berhasil dibuat.
