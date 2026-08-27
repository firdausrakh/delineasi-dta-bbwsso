@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
%PY% scripts\verify_r2.py
if errorlevel 1 exit /b %errorlevel%
echo.
echo VERIFY R2 PASS.
