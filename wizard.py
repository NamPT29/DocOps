"""First-run configuration wizard for the packaged Windows host."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import tkinter as tk
from tkinter import messagebox
from urllib.parse import quote

from server.host_runtime_paths import HostRuntimePaths


def _quote_env_value(value: object) -> str:
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def build_host_environment(
    *,
    paths: HostRuntimePaths,
    database_host: str,
    database_port: int,
    database_name: str,
    database_user: str,
    database_password: str,
    admin_password: str,
    web_port: int,
) -> str:
    """Build host.env without placing secrets in the application directory."""
    encoded_user = quote(database_user, safe="")
    encoded_password = quote(database_password, safe="")
    database_url = (
        f"postgresql+psycopg://{encoded_user}:{encoded_password}"
        f"@{database_host}:{database_port}/{database_name}"
    )
    values = {
        "APP_ENV": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "INITIAL_ADMIN_PASSWORD": admin_password,
        "DATABASE_URL": database_url,
        "DB_POOL_SIZE": "5",
        "DB_MAX_OVERFLOW": "2",
        "DB_POOL_TIMEOUT": "30",
        "DB_POOL_RECYCLE": "1800",
        "HOST": "0.0.0.0",
        "PORT": str(web_port),
        "OPEN_BROWSER": "true",
        "PDF_STORAGE_PATH": str(paths.uploads_dir.resolve()),
        "TEMPLATE_STORAGE_PATH": str(paths.templates_dir.resolve()),
        "DOCUMENT_SOURCE_ROOT": str(paths.source_documents_dir.resolve()),
        "EXPORT_WORK_DIR": str(paths.exports_dir.resolve()),
        "LOG_DIR": str(paths.logs_dir.resolve()),
        "API_DOCS_ENABLED": "false",
        "CORS_ORIGINS": "",
    }
    return "\n".join(
        f"{key}={_quote_env_value(value)}" for key, value in values.items()
    ) + "\n"


def run_setup_wizard(
    env_path: str | Path,
    paths: HostRuntimePaths | None = None,
) -> bool:
    """Collect external PostgreSQL settings and atomically write host.env."""
    target_path = Path(env_path)
    runtime_paths = paths or HostRuntimePaths(target_path.parent.parent)
    saved = False

    root = tk.Tk()
    root.title("ScanToExcel - Thiet lap lan dau")
    root.geometry("480x620")
    root.resizable(False, False)

    tk.Label(root, text="SCAN TO EXCEL HOST", font=("Arial", 15, "bold")).pack(pady=12)
    tk.Label(
        root,
        text=(
            "PostgreSQL phai duoc cai va dang chay tren may nay.\n"
            "Nhap thong tin database da tao cho ung dung."
        ),
        justify="center",
    ).pack(pady=4)

    form = tk.Frame(root)
    form.pack(fill="x", padx=45, pady=10)

    def add_entry(label: str, default: str, *, secret: bool = False) -> tk.Entry:
        tk.Label(form, text=label, anchor="w").pack(fill="x")
        entry = tk.Entry(form, width=45, show="*" if secret else "")
        entry.insert(0, default)
        entry.pack(fill="x", pady=(2, 8))
        return entry

    db_host_entry = add_entry("PostgreSQL host", "127.0.0.1")
    db_port_entry = add_entry("PostgreSQL port", "5432")
    db_name_entry = add_entry("Database", "scan_data")
    db_user_entry = add_entry("Database user", "postgres")
    db_password_entry = add_entry("Database password", "", secret=True)
    admin_password_entry = add_entry(
        "Mat khau admin ban dau (toi thieu 12 ky tu)", "", secret=True
    )
    web_port_entry = add_entry("Cong noi bo cua ung dung", "8000")

    def on_submit() -> None:
        nonlocal saved
        db_host = db_host_entry.get().strip()
        db_name = db_name_entry.get().strip()
        db_user = db_user_entry.get().strip()
        db_password = db_password_entry.get()
        admin_password = admin_password_entry.get()

        try:
            db_port = int(db_port_entry.get().strip())
            web_port = int(web_port_entry.get().strip())
        except ValueError:
            messagebox.showerror("Loi", "Port PostgreSQL va port Web phai la so.")
            return
        if not all((db_host, db_name, db_user, db_password)):
            messagebox.showerror("Loi", "Hay nhap day du thong tin PostgreSQL.")
            return
        if not 1 <= db_port <= 65535 or not 1 <= web_port <= 65535:
            messagebox.showerror("Loi", "Port phai nam trong khoang 1-65535.")
            return
        if len(admin_password) < 12:
            messagebox.showerror("Loi", "Mat khau admin phai co it nhat 12 ky tu.")
            return

        content = build_host_environment(
            paths=runtime_paths,
            database_host=db_host,
            database_port=db_port,
            database_name=db_name,
            database_user=db_user,
            database_password=db_password,
            admin_password=admin_password,
            web_port=web_port,
        )
        runtime_paths.ensure_directories()
        temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, target_path)
        saved = True
        messagebox.showinfo(
            "Thanh cong",
            "Da luu host.env. Ung dung se kiem tra PostgreSQL va khoi dong.",
        )
        root.destroy()

    tk.Button(
        root,
        text="Luu cau hinh",
        command=on_submit,
        bg="#165DFF",
        fg="white",
        font=("Arial", 10, "bold"),
    ).pack(pady=12)
    root.mainloop()
    return saved and target_path.exists()
