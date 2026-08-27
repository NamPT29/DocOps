@echo off
setlocal
chcp 65001 >nul
title SỐ HÓA - HOST SERVER
mode con: cols=112 lines=38 >nul 2>&1
echo ==============================================
echo KHOI DONG MAY CHU SO HOA ALL IN ONE
echo ==============================================

echo Kiem tra ket noi PostgreSQL...
python -c "from sqlalchemy import text; from server.database import engine; connection = engine.connect(); connection.execute(text('SELECT 1')); connection.close()" >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong ket noi duoc PostgreSQL theo DATABASE_URL trong file .env!
    echo Vui long kiem tra dich vu PostgreSQL va cau hinh DATABASE_URL.
    echo He thong dung lai de tranh thong bao san sang gia.
    pause
    exit /b 1
)

set "CADDY_EXE="
for /f "delims=" %%I in ('where caddy.exe 2^>nul') do if not defined CADDY_EXE set "CADDY_EXE=%%I"
if not defined CADDY_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\CaddyServer.Caddy_*") do (
        if exist "%%~fD\caddy.exe" set "CADDY_EXE=%%~fD\caddy.exe"
    )
)

netstat -ano | findstr /R /C:":80 .*LISTENING" >nul
if errorlevel 1 (
    if not defined CADDY_EXE (
        echo [LOI] Khong tim thay Caddy. Hay cai dat Caddy hoac them caddy.exe vao PATH.
        pause
        exit /b 1
    )
    echo Dang khoi dong Caddy tai cong 80...
    start "" /b "%CADDY_EXE%" run --config "%~dp0Caddyfile" --adapter caddyfile
    timeout /t 2 /nobreak >nul
    netstat -ano | findstr /R /C:":80 .*LISTENING" >nul
    if errorlevel 1 (
        echo [LOI] Caddy khong khoi dong duoc. Kiem tra Caddyfile.
        pause
        exit /b 1
    )
)

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo [THONG BAO] FastAPI da chay tai cong 8000; Caddy dang phuc vu tai cong 80.
    echo Dang mo trang quan ly hien tai qua Caddy...
    start "" http://127.0.0.1/login.html
    echo.
    echo Nhan phim bat ky de dong cua so nay. Server van tiep tuc chay nen.
    pause >nul
    exit /b 0
)

echo.
echo Dang khoi dong he thong...
echo.
echo =========================================================
echo Dang khoi dong FastAPI...
echo 2. Cac may khac mo trinh duyet va go: http://Dia_chi_IP
echo.
echo (LUU Y: DUNG TAT CUA SO NAY TRONG SUOT QUA TRINH LAM VIEC)
echo =========================================================
echo.
python -X utf8 -u host_console.py
if errorlevel 1 echo [LOI] FastAPI khong khoi dong duoc. Kiem tra PostgreSQL, DATABASE_URL va log o tren.
pause
