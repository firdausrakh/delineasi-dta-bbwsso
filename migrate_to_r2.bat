@echo off
setlocal
cd /d "%~dp0"
call export_r2_bundle.bat
if errorlevel 1 exit /b %errorlevel%
call upload_r2.bat
if errorlevel 1 exit /b %errorlevel%
call verify_r2.bat
if errorlevel 1 exit /b %errorlevel%
echo.
echo ===============================================
echo MIGRASI DATA LOKAL KE R2 SELESAI DAN TERVERIFIKASI
echo Selanjutnya set DATA_BACKEND=r2 pada Vercel.
echo ===============================================
