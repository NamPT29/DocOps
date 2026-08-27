import tkinter as tk
from tkinter import messagebox
import secrets
import os

def run_setup_wizard(env_path: str):
    """Bật giao diện điền thông tin và lưu ra file .env"""
    root = tk.Tk()
    root.title("ScanToExcel - Khởi tạo hệ thống lần đầu")
    root.geometry("400x350")
    
    tk.Label(root, text="Chào mừng đến với ScanToExcel", font=("Arial", 14, "bold")).pack(pady=10)
    tk.Label(root, text="Phần mềm cần vài thông tin để thiết lập lần đầu:").pack(pady=5)
    
    # Port
    tk.Label(root, text="Cổng mạng (Port) chạy Web:").pack()
    port_entry = tk.Entry(root, width=30)
    port_entry.insert(0, "80")
    port_entry.pack(pady=5)
    
    # Mật khẩu DB
    tk.Label(root, text="Mật khẩu Database (Tự đặt):").pack()
    db_pw_entry = tk.Entry(root, width=30)
    db_pw_entry.insert(0, "MatKhauDB_123")
    db_pw_entry.pack(pady=5)
    
    # Mật khẩu Admin khởi tạo
    tk.Label(root, text="Mật khẩu Admin hệ thống (Ít nhất 12 ký tự):").pack()
    admin_pw_entry = tk.Entry(root, width=30)
    admin_pw_entry.insert(0, "Admin@ScanToExcel2024")
    admin_pw_entry.pack(pady=5)
    
    result_data = {}
    
    def on_submit():
        port = port_entry.get().strip()
        db_pw = db_pw_entry.get().strip()
        admin_pw = admin_pw_entry.get().strip()
        
        if not port or not port.isdigit():
            messagebox.showerror("Lỗi", "Cổng mạng phải là số (VD: 80)")
            return
        if len(admin_pw) < 12:
            messagebox.showerror("Lỗi", "Mật khẩu Admin phải dài ít nhất 12 ký tự")
            return
            
        result_data['port'] = port
        result_data['db_pw'] = db_pw
        result_data['admin_pw'] = admin_pw
        
        # Sinh file .env
        secret_key = secrets.token_hex(32)
        env_content = f"""APP_ENV=production
SECRET_KEY={secret_key}
INITIAL_ADMIN_PASSWORD={admin_pw}
DB_PASSWORD={db_pw}
DATABASE_URL=postgresql+psycopg://postgres:{db_pw}@127.0.0.1:5433/postgres
UVICORN_WORKERS=4
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
HOST=0.0.0.0
PORT={port}
PDF_STORAGE_PATH=uploads
TEMPLATE_STORAGE_PATH=templates
DOCUMENT_SOURCE_ROOT=source_documents
EXPORT_WORK_DIR=exports
API_DOCS_ENABLED=false
CORS_ORIGINS=
"""
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)
            
        messagebox.showinfo("Thành công", "Đã lưu cấu hình. Hệ thống sẽ bắt đầu khởi động!")
        root.destroy()

    tk.Button(root, text="Lưu và Khởi động", command=on_submit, bg="blue", fg="white", font=("Arial", 10, "bold")).pack(pady=20)
    
    # Chạy vòng lặp giao diện, chặn cho đến khi tắt
    root.mainloop()
    
    return os.path.exists(env_path)
