@echo off
echo ==============================================
echo KHOI DONG MAY CHU SO HOA ALL IN ONE
echo ==============================================

echo Kiem tra ket noi MySQL...
netstat -an | find "3306" >nul
if errorlevel 1 (
    echo [CANH BAO] Khong tim thay MySQL dang chay!
    echo Vui long mo XAMPP Control Panel va Start MySQL.
    echo Bam phim bat ky de tiep tuc sau khi da Start MySQL...
    pause >nul
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
echo HE THONG DA SAN SANG! 
echo De cac may khac trong cong ty truy cap vao duoc:
echo 1. Kiem tra IP cua may nay (vd: 192.168.31.24)
echo 2. Cac may khac mo trinh duyet va go: http://Dia_chi_IP
echo.
echo (LUU Y: DUNG TAT CUA SO NAY TRONG SUOT QUA TRINH LAM VIEC)
echo =========================================================
echo.
python -m uvicorn server.main:app --host 0.0.0.0 --port 80
pause
