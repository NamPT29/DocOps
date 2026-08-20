@echo off
setlocal
chcp 65001 >nul
title SỐ HÓA - HOST SERVER
mode con: cols=145 lines=42 >nul 2>&1
echo ==============================================
echo KHOI DONG MAY CHU SO HOA ALL IN ONE
echo ==============================================

echo Kiem tra ket noi PostgreSQL...
python -c "from sqlalchemy import text; from server.database import engine; connection = engine.connect(); connection.execute(text('SELECT 1')); connection.close()" >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong ket noi duoc PostgreSQL theo DATABASE_URL trong file .env!
    echo Vui long kiem tra dich vu PostgreSQL va cau hinh DATABASE_URL.
    echo He thong dung lai de tranh thong bao san sang gia.
    exit /b 1
)

netstat -ano | findstr /R /C:":80 .*LISTENING" >nul
if not errorlevel 1 (
    echo [THONG BAO] May chu da chay hoac cong 80 dang duoc su dung.
    echo Dang mo trang quan ly hien tai...
    start "" http://127.0.0.1
    exit /b 0
)

echo.
echo Dang khoi dong he thong...
echo.
echo =========================================================
echo Dang khoi dong FastAPI...
echo De cac may khac trong cong ty truy cap vao duoc:
echo 1. Kiem tra IP cua may nay (vd: 192.168.31.24)
echo 2. Cac may khac mo trinh duyet va go: http://Dia_chi_IP
echo.
echo (LUU Y: DUNG TAT CUA SO NAY TRONG SUOT QUA TRINH LAM VIEC)
echo =========================================================
echo.
python -X utf8 -u host_console.py
if errorlevel 1 echo [LOI] FastAPI khong khoi dong duoc. Kiem tra PostgreSQL, DATABASE_URL va log o tren.
pause
