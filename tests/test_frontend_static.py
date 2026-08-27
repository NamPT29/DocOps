from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.frontend_static import PublicFrontendStaticFiles, resolve_public_frontend_file


def test_frontend_mount_does_not_serve_private_temp_page(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("public", encoding="utf-8")
    (frontend_dir / "temp.html").write_text("private", encoding="utf-8")
    app = FastAPI()
    app.mount("/frontend", PublicFrontendStaticFiles(directory=frontend_dir))
    client = TestClient(app)

    assert client.get("/frontend/index.html").status_code == 200
    assert client.get("/frontend/temp.html").status_code == 404
    assert client.get("/frontend/TEMP.html").status_code == 404


def test_root_file_resolver_blocks_temp_and_path_traversal(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    public_file = frontend_dir / "index.html"
    public_file.write_text("public", encoding="utf-8")
    (frontend_dir / "temp.html").write_text("private", encoding="utf-8")
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside", encoding="utf-8")

    assert resolve_public_frontend_file(frontend_dir, "index.html") == public_file.resolve()
    assert resolve_public_frontend_file(frontend_dir, "temp.html") is None
    assert resolve_public_frontend_file(frontend_dir, "./TEMP.html") is None
    assert resolve_public_frontend_file(frontend_dir, "../outside.txt") is None
