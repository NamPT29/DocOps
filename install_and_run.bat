@echo off
echo ==============================================
echo KHOI DONG HE THONG SCAN TO EXCEL
echo ==============================================

echo [1] Kiem tra ket noi MySQL...
:: Simple check if port 3306 is listening (Requires MySQL to be running)
netstat -an | find "3306" >nul
if errorlevel 1 (
    echo [CANH BAO] Khong tim thay MySQL dang chay!
    echo Vui long mo XAMPP Control Panel va Start MySQL.
    echo Bam phim bat ky de tiep tuc sau khi da Start MySQL...
    pause >nul
)

echo.
echo [2] Cai dat cac thu vien Python...
pip install -r requirements.txt

echo.
echo [3] Khởi dong may chu...
echo Dang chay Uvicorn, vui long khong tat cua so nay!
echo Truy cap: http://localhost
echo.
python -m uvicorn server.main:app --host 0.0.0.0 --port 80
pause
