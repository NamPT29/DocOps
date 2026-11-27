"""Local Windows demo. Install requirements.txt and pgserver, then run
python scripts/run_demo.py <dedicated-demo-directory> [--check].
Only use synthetic data in this loopback-only development instance.
"""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(root)
    from pgserver import get_server

    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    data = root / "pgdata"
    data.mkdir(exist_ok=True)
    password = os.environ.get("DOCOPS_DEMO_PASSWORD") or getpass.getpass("Demo admin password (12+ chars): ")
    if len(password) < 12:
        parser.error("Demo admin password must have at least 12 characters")
    pg = get_server(data)
    os.environ.update(APP_ENV="development", DATABASE_URL=pg.get_uri().replace("postgresql:", "postgresql+psycopg:"),
                      INITIAL_ADMIN_PASSWORD=password, SECRET_KEY=secrets.token_urlsafe(48), REDIS_URL="", PORT="8000")
    for key in ("PDF_STORAGE_PATH", "TEMPLATE_STORAGE_PATH", "DOCUMENT_SOURCE_ROOT", "HANDOVER_DIR", "EXPORT_WORK_DIR", "LOG_DIR"):
        path = root / key.lower()
        path.mkdir(exist_ok=True)
        os.environ[key] = str(path)
    from shutil import copyfile
    template = Path(os.environ["TEMPLATE_STORAGE_PATH"]) / "UBND.xlsx"
    if not template.exists():
        copyfile(repo / "templates/UBND.xlsx", template)
    for script in ("migrate_database.py", "preflight.py"):
        subprocess.run([sys.executable, str(repo / "scripts" / script)], check=True)
    if args.check:
        from fastapi.testclient import TestClient
        from server.main import app
        with TestClient(app) as client:
            for response in (client.get("/health/ready"), client.post("/api/login", json={"username":"admin","password":password})):
                response.raise_for_status()
                print(response.request.url.path, response.status_code)
    else:
        import uvicorn
        uvicorn.run("server.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
