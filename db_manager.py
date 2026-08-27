import os
import subprocess
import time
import sys

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def init_and_start_db(port: int, password: str, max_connections: int = 200) -> bool:
    """Khởi tạo và chạy PostgreSQL."""
    base_dir = get_base_dir()
    pg_bin_dir = os.path.join(base_dir, "database_engine", "bin")
    pg_data_dir = os.path.join(base_dir, "database_engine", "data")
    
    initdb_exe = os.path.join(pg_bin_dir, "initdb.exe")
    pg_ctl_exe = os.path.join(pg_bin_dir, "pg_ctl.exe")
    
    if not os.path.exists(initdb_exe):
        print(f"Lỗi: Không tìm thấy PostgreSQL tại {initdb_exe}")
        return False

    # Khởi tạo DB nếu chưa có
    if not os.path.exists(pg_data_dir):
        print("Đang khởi tạo Cơ sở dữ liệu lần đầu...")
        
        # Ghi mật khẩu ra file tạm để initdb đọc
        pw_file = os.path.join(base_dir, "pg_pw.txt")
        with open(pw_file, "w") as f:
            f.write(password)
            
        try:
            subprocess.run([
                initdb_exe,
                "-D", pg_data_dir,
                "-U", "postgres",
                "--pwfile", pw_file,
                "-A", "scram-sha-256",
                "-E", "utf8"
            ], check=True, stdout=subprocess.DEVNULL)
        finally:
            if os.path.exists(pw_file):
                os.remove(pw_file)
                
        # Sửa cấu hình max_connections
        conf_file = os.path.join(pg_data_dir, "postgresql.conf")
        if os.path.exists(conf_file):
            with open(conf_file, "a") as f:
                f.write(f"\nmax_connections = {max_connections}\n")

    # Khởi động CSDL
    print("Đang khởi động Cơ sở dữ liệu...")
    try:
        subprocess.run([
            pg_ctl_exe,
            "start",
            "-D", pg_data_dir,
            "-w", # Wait for start
            "-t", "60", # Timeout 60s
            "-o", f"-p {port}" # Override port
        ], check=True, stdout=subprocess.DEVNULL)
        print("Cơ sở dữ liệu đã chạy!")
        return True
    except subprocess.CalledProcessError:
        print("Lỗi: Không thể khởi động CSDL.")
        return False

def stop_db():
    """Tắt PostgreSQL."""
    base_dir = get_base_dir()
    pg_ctl_exe = os.path.join(base_dir, "database_engine", "bin", "pg_ctl.exe")
    pg_data_dir = os.path.join(base_dir, "database_engine", "data")
    
    if os.path.exists(pg_data_dir) and os.path.exists(pg_ctl_exe):
        print("Đang tắt Cơ sở dữ liệu...")
        subprocess.run([
            pg_ctl_exe,
            "stop",
            "-D", pg_data_dir,
            "-m", "fast"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
