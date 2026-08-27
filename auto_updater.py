import os
import urllib.request
import json
import zipfile
import threading
import time
import subprocess
import sys

# URL giả lập nơi chứa file cấu hình cập nhật
# Ví dụ cấu trúc file JSON: {"version": "1.1", "url": "https://example.com/update_v1_1.zip"}
UPDATE_INFO_URL = "https://your-domain.com/update/version.json"
CURRENT_VERSION = "1.0"

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def check_for_updates():
    """Kiểm tra xem có bản cập nhật mới không."""
    try:
        with urllib.request.urlopen(UPDATE_INFO_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            latest_version = data.get("version")
            download_url = data.get("url")
            
            if latest_version and latest_version != CURRENT_VERSION:
                print(f"[*] Có phiên bản mới: {latest_version}. Đang tiến hành tải xuống...")
                return download_url
    except Exception as e:
        print(f"Không thể kiểm tra cập nhật: {e}")
    return None

def apply_update(download_url):
    """Tải và áp dụng bản cập nhật."""
    base_dir = get_base_dir()
    update_zip = os.path.join(base_dir, "update.zip")
    
    try:
        print("[*] Đang tải bản cập nhật...")
        urllib.request.urlretrieve(download_url, update_zip)
        print("[*] Tải xong. Chuẩn bị giải nén và ghi đè...")
        
        # Viết file batch để tự động giải nén đè và khởi động lại
        # Vì file exe hiện tại đang chạy không thể tự ghi đè chính nó, 
        # ta cần một file batch chạy độc lập để làm việc này.
        bat_script = os.path.join(base_dir, "apply_update.bat")
        exe_name = os.path.basename(sys.executable) if getattr(sys, 'frozen', False) else "app_launcher.py"
        
        script_content = f"""@echo off
timeout /t 3 /nobreak >nul
echo Dang ap dung ban cap nhat...
powershell -Command "Expand-Archive -Path 'update.zip' -DestinationPath '.' -Force"
del update.zip
echo Hoan tat! Dang khoi dong lai phan mem...
start "" "{exe_name}"
del "%~f0"
"""
        with open(bat_script, "w") as f:
            f.write(script_content)
            
        print("[*] Bắt đầu khởi động lại để cập nhật...")
        # Chạy file batch và thoát phần mềm hiện tại
        subprocess.Popen([bat_script], shell=True)
        sys.exit(0)
        
    except Exception as e:
        print(f"Lỗi khi cập nhật: {e}")
        if os.path.exists(update_zip):
            os.remove(update_zip)

def auto_update_loop():
    """Luồng chạy ngầm tự động kiểm tra mỗi 12 tiếng."""
    while True:
        url = check_for_updates()
        if url:
            apply_update(url)
        time.sleep(12 * 3600)

def start_auto_updater():
    """Khởi động luồng kiểm tra cập nhật tự động."""
    thread = threading.Thread(target=auto_update_loop, daemon=True)
    thread.start()
