@echo off
chcp 65001 >nul
title Scan To Excel Host
cd /d "%~dp0"
ScanToExcelApp.exe
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo Scan To Excel Host da dung voi ma loi %APP_EXIT_CODE%.
    echo Kiem tra thong bao phia tren, sau do nhan phim bat ky de dong.
    pause >nul
)
exit /b %APP_EXIT_CODE%
