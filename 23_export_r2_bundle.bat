@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
echo Memeriksa dan membundel DEM, PL, CN, plen, streams_analysis, dan landsystem untuk runtime R2...
%PY% scripts\export_local_to_r2.py --overwrite
if errorlevel 1 exit /b %errorlevel%
echo.
echo Bundle R2 termasuk layer analisis morfometri berhasil dibuat.
