"""Check scan (lát CS1): xem file và trang của gói scan, so số trang với số tờ mục lục."""
import hashlib
from datetime import datetime

import pypdf
import pytest
from pypdf.generic import DecodedStreamObject
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app
from server.models import ArrangementDossier, Project, ProjectCase, Template, User
from server.models_scan import CaseScanFile, CaseScanPackage
from server.models_workflow import CaseStageState, ProjectStageMember
from server.routers.auth import get_admin_user, get_current_user
from server.services import scan_check_service
from server.services.scan_check_service import dossier_page_status, to_pdf_point

client = TestClient(app)
A4 = (595, 842)


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scan-check.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _as(user):
    return {"id": user.id, "username": user.username, "full_name": user.full_name,
            "role": user.role, "session_id": "s-test"}


def _write_pdf(path, pages):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=A4[0], height=A4[1])
    with open(path, "wb") as handle:
        writer.write(handle)


def _dossier(project, case, number, sheets, suffix=""):
    return ArrangementDossier(
        project_id=project.id, case_id=case.id, box_number=1, dossier_number=number,
        dossier_suffix=suffix, fonds_code="F1", fonds_name="F1", catalog_number="1",
        title=f"Hồ sơ {number}", start_date="01/01/2000", end_date="31/12/2000",
        start_year=2000, maintenance_code="V", sheet_count=sheets, source_row=number,
    )


@pytest.fixture()
def env(database, tmp_path, monkeypatch):
    db = database
    root = tmp_path / "samples_local"
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(root))

    admin = User(username="admin", password="x", full_name="Admin", role="admin")
    staff = User(username="hc", password="x", full_name="Hành chính", role="user", account_type="staff")
    ctv = User(username="ctv", password="x", full_name="Cộng tác viên", role="user", account_type="ctv")
    db.add_all([admin, staff, ctv, Template(name="T", filename="t.xlsx")])
    db.commit()
    project = Project(
        name="P1", root_folder_name="P1", template_id=1, template_name_snapshot="T",
        template_filename_snapshot="t.xlsx", case_level=1, report_mode="pdf",
        created_by_user_id=admin.id, status="new",
    )
    db.add(project)
    db.commit()
    case = ProjectCase(project_id=project.id, case_key="P1/Hộp 01", display_name="Hộp 01")
    other_case = ProjectCase(project_id=project.id, case_key="P1/Hộp 02", display_name="Hộp 02")
    db.add_all([case, other_case])
    db.commit()

    db.add_all([
        _dossier(project, case, 1, 3),
        _dossier(project, case, 2, 2),
        _dossier(project, case, 3, 1),
        _dossier(project, case, 4, 5),
    ])
    box = root / "P1" / "Hộp 01"
    layout = {
        "01/BIA.pdf": 1, "01/1.pdf": 2, "01/2.pdf": 1, "01/10.pdf": 1,
        "02/1.pdf": 1,
        "03/1.pdf": 4,
        "04/1.pdf": 3, "04/2.pdf": 1,
        "07/1.pdf": 2,
        "ghichu.pdf": 1,
    }
    for rel, pages in layout.items():
        _write_pdf(box / rel, pages)
    (box / "01" / "Thumbs.db").write_bytes(b"x")

    package = CaseScanPackage(case_id=case.id, version=1, source_path="P1/Hộp 01",
                              status="done", submitted_by_user_id=admin.id)
    other_package = CaseScanPackage(case_id=other_case.id, version=1, source_path="P1/Hộp 01",
                                    status="done", submitted_by_user_id=admin.id)
    db.add_all([package, other_package])
    db.commit()
    files = {}
    for rel, pages in layout.items():
        files[rel] = CaseScanFile(package_id=package.id, relative_path=rel, page_count=pages,
                                  status="ok", is_pdf=True)
    files["04/2.pdf"].page_count = -1
    files["04/2.pdf"].status = "incomplete"
    files["01/Thumbs.db"] = CaseScanFile(package_id=package.id, relative_path="01/Thumbs.db",
                                         page_count=0, status="not_pdf", is_pdf=False)
    other_file = CaseScanFile(package_id=other_package.id, relative_path="01/1.pdf",
                              page_count=2, status="ok", is_pdf=True)
    db.add_all(list(files.values()) + [other_file])
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: _as(admin)
    app.dependency_overrides[get_current_user] = lambda: _as(admin)
    yield {
        "db": db, "root": root, "box": box, "project": project, "case": case,
        "other_case": other_case, "package": package, "other_package": other_package,
        "files": files, "other_file": other_file, "admin": admin, "staff": staff, "ctv": ctv,
    }
    app.dependency_overrides.clear()


def _view_url(env, case=None, package=None):
    case = case or env["case"]
    package = package or env["package"]
    return f"/api/projects/{env['project'].id}/cases/{case.id}/scan-packages/{package.id}/check-view"


def _file_url(env, file_id, case=None, package=None):
    case = case or env["case"]
    package = package or env["package"]
    return f"/api/projects/{env['project'].id}/cases/{case.id}/scan-packages/{package.id}/files/{file_id}"


@pytest.mark.parametrize("sheets,pages,unknown,expected", [
    (3, 4, False, ("ok", 4, 7)),
    (3, 3, False, ("missing", 4, 7)),
    (3, 7, False, ("ok", 4, 7)),
    (3, 8, False, ("over", 4, 7)),
    (3, 9, True, ("unknown", 4, 7)),
    (None, 5, False, ("no_catalog", None, None)),
    (0, 5, False, ("no_catalog", None, None)),
])
def test_dossier_page_status_bounds(sheets, pages, unknown, expected):
    assert dossier_page_status(sheets, pages, unknown) == expected


def test_check_view_groups_files_and_compares_pages_with_catalog(env):
    res = client.get(_view_url(env))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["package"] == {"id": env["package"].id, "version": 1, "status": "done"}

    by_folder = {d["folder"]: d for d in data["dossiers"]}
    assert [d["folder"] for d in data["dossiers"]] == ["01", "02", "03", "04", "07"]

    first = by_folder["01"]
    assert (first["sheets"], first["min_pages"], first["max_pages"], first["pages"]) == (3, 4, 7, 5)
    assert first["status"] == "ok"
    assert first["has_cover"] is True
    assert [f["name"] for f in first["files"]] == ["BIA.pdf", "1.pdf", "2.pdf", "10.pdf", "Thumbs.db"]
    assert first["files"][0]["is_cover"] is True
    assert first["files"][-1]["is_pdf"] is False

    assert (by_folder["02"]["status"], by_folder["02"]["pages"], by_folder["02"]["min_pages"]) == ("missing", 1, 3)
    assert by_folder["02"]["has_cover"] is False
    assert (by_folder["03"]["status"], by_folder["03"]["pages"], by_folder["03"]["max_pages"]) == ("over", 4, 3)
    assert by_folder["04"]["status"] == "unknown"
    assert by_folder["04"]["pages"] == 3
    assert (by_folder["07"]["status"], by_folder["07"]["sheets"]) == ("no_catalog", None)

    assert [f["relative_path"] for f in data["misplaced_files"]] == ["ghichu.pdf"]


def test_check_view_ignores_catalog_rows_removed_from_last_import(env):
    db = env["db"]
    row = db.query(ArrangementDossier).filter_by(case_id=env["case"].id, dossier_number=2).one()
    row.missing_from_import_id = 1
    db.commit()
    data = client.get(_view_url(env)).json()["data"]
    second = next(d for d in data["dossiers"] if d["folder"] == "02")
    assert second["status"] == "no_catalog"


def test_scan_file_streams_pdf_from_package_folder(env):
    scan_file = env["files"]["01/1.pdf"]
    res = client.get(_file_url(env, scan_file.id))
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["cache-control"] == "no-store"
    assert res.content == (env["box"] / "01" / "1.pdf").read_bytes()
    assert len(pypdf.PdfReader(env["box"] / "01" / "1.pdf").pages) == 2


def test_package_of_another_case_is_not_found(env):
    assert client.get(_view_url(env, package=env["other_package"])).status_code == 404
    assert client.get(_file_url(env, env["other_file"].id, package=env["other_package"])).status_code == 404
    # A file of another package cannot be read through this package.
    assert client.get(_file_url(env, env["other_file"].id)).status_code == 404


def test_non_pdf_and_missing_files_are_not_served(env):
    assert client.get(_file_url(env, env["files"]["01/Thumbs.db"].id)).status_code == 404
    (env["box"] / "02" / "1.pdf").unlink()
    assert client.get(_file_url(env, env["files"]["02/1.pdf"].id)).status_code == 404


def test_file_path_outside_package_folder_is_refused(env):
    db = env["db"]
    _write_pdf(env["root"] / "P1" / "secret.pdf", 1)
    escape = CaseScanFile(package_id=env["package"].id, relative_path="../secret.pdf",
                          page_count=1, status="ok", is_pdf=True)
    db.add(escape)
    db.commit()
    res = client.get(_file_url(env, escape.id))
    assert res.status_code == 400
    assert b"%PDF" not in res.content


def test_permissions_follow_scan_and_scan_qc_membership(env):
    db = env["db"]
    project = env["project"]
    scan_file = env["files"]["01/1.pdf"]

    app.dependency_overrides[get_current_user] = lambda: _as(env["staff"])
    assert client.get(_view_url(env)).status_code == 403
    assert client.get(_file_url(env, scan_file.id)).status_code == 403

    db.add(ProjectStageMember(project_id=project.id, user_id=env["staff"].id, stage_key="scan_qc"))
    db.commit()
    assert client.get(_view_url(env)).status_code == 200
    assert client.get(_file_url(env, scan_file.id)).status_code == 200

    db.add(ProjectStageMember(project_id=project.id, user_id=env["ctv"].id, stage_key="scan_qc"))
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as(env["ctv"])
    assert client.get(_view_url(env)).status_code == 403
    assert client.get(_file_url(env, scan_file.id)).status_code == 403


# --- Bôi trắng vết ghim (CS2) ------------------------------------------------------

MARK = b"0 0 0 rg 50 750 40 40 re f"


def _write_marked_pdf(path, pages=2, rotate=0):
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=A4[0], height=A4[1])
        stream = DecodedStreamObject()
        stream.set_data(MARK)
        page.replace_contents(stream)
        if rotate:
            page.rotate(rotate)
    with open(path, "wb") as handle:
        writer.write(handle)


def _start_check_scan(env, user=None, status="in_progress"):
    user = user or env["staff"]
    db = env["db"]
    db.add(ProjectStageMember(project_id=env["project"].id, user_id=env["staff"].id, stage_key="scan_qc"))
    db.add(CaseStageState(project_id=env["project"].id, case_id=env["case"].id, stage_key="scan_qc",
                          status=status, assigned_user_id=user.id, rework_count=0))
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as(env["staff"])


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _whiteout(env, scan_file, **body):
    payload = {"page": 1, "base_sha256": "", "strokes": [{"width": 0.03, "points": [[0.1, 0.1], [0.2, 0.1]]}]}
    payload.update(body)
    return client.post(f"{_file_url(env, scan_file.id)}/whiteout", json=payload)


@pytest.fixture()
def marked(env):
    path = env["box"] / "01" / "1.pdf"
    _write_marked_pdf(path)
    return path


@pytest.mark.parametrize("rotation,point,expected", [
    (0, (0, 0), (0, 800)),
    (0, (1, 1), (600, 0)),
    (90, (0, 0), (0, 0)),
    (90, (1, 0), (0, 800)),
    (180, (0, 0), (600, 0)),
    (270, (0, 0), (600, 800)),
    (270, (0, 1), (0, 800)),
    (-90, (0, 0), (600, 800)),
])
def test_to_pdf_point_follows_page_rotation(rotation, point, expected):
    assert to_pdf_point(*point, (0, 0, 600, 800), rotation) == expected


def test_to_pdf_point_uses_crop_box_origin():
    assert to_pdf_point(0.5, 0.5, (10, 20, 610, 820), 0) == (310, 420)


def test_file_response_carries_sha256(env, marked):
    res = client.get(_file_url(env, env["files"]["01/1.pdf"].id))
    assert res.headers["x-scan-file-sha256"] == _sha(marked)


def test_whiteout_overwrites_page_with_white_strokes(env, marked):
    _start_check_scan(env)
    scan_file = env["files"]["01/1.pdf"]
    view = client.get(_view_url(env)).json()["data"]
    assert view["can_whiteout"] is True and view["whiteout_hint"] == ""

    res = _whiteout(env, scan_file, base_sha256=_sha(marked))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["sha256"] == _sha(marked)
    assert data["file_size"] == marked.stat().st_size
    env["db"].refresh(scan_file)
    assert (scan_file.sha256, scan_file.file_size) == (data["sha256"], data["file_size"])

    reader = pypdf.PdfReader(marked)
    assert len(reader.pages) == 2
    content = reader.pages[0].get_contents().get_data().decode("ascii")
    assert content.startswith("q\n" + MARK.decode() + "\nQ\n"), "nội dung scan cũ giữ nguyên, bọc q/Q"
    tail = content.split("\nQ\n", 1)[1].split("\n")
    assert tail[:4] == ["q", "1 1 1 RG", "1 J", "1 j"]
    assert tail[4:8] == ["17.85 w", "59.50 757.80 m", "119.00 757.80 l", "S"]
    assert reader.pages[1].get_contents().get_data() == MARK, "trang khác không đổi"
    assert sorted(p.name for p in marked.parent.iterdir()) == ["1.pdf", "10.pdf", "2.pdf", "BIA.pdf", "Thumbs.db"]


def test_whiteout_single_point_and_rotated_page(env):
    path = env["box"] / "01" / "2.pdf"
    _write_marked_pdf(path, pages=1, rotate=90)
    _start_check_scan(env)
    res = _whiteout(env, env["files"]["01/2.pdf"], base_sha256=_sha(path),
                    strokes=[{"width": 0.03, "points": [[0.1, 0.1]]}])
    assert res.status_code == 200, res.text
    tail = pypdf.PdfReader(path).pages[0].get_contents().get_data().decode().split("\nQ\n", 1)[1].split("\n")
    # Trang xoay 90: bề ngang đang hiển thị là cạnh 842 của trang.
    assert tail[4:8] == ["25.26 w", "59.50 84.20 m", "59.50 84.20 l", "S"]


def test_whiteout_refuses_stale_file(env, marked):
    _start_check_scan(env)
    before = marked.read_bytes()
    res = _whiteout(env, env["files"]["01/1.pdf"], base_sha256="0" * 64)
    assert res.status_code == 409
    assert "đã thay đổi" in res.json()["detail"]
    assert marked.read_bytes() == before


def test_whiteout_needs_check_scan_in_progress(env, marked):
    scan_file = env["files"]["01/1.pdf"]
    view = client.get(_view_url(env)).json()["data"]
    assert view["can_whiteout"] is False
    assert "Bắt đầu Check scan" in view["whiteout_hint"]
    assert _whiteout(env, scan_file, base_sha256=_sha(marked)).status_code == 409

    _start_check_scan(env, status="done")
    assert client.get(_view_url(env)).json()["data"]["can_whiteout"] is False
    before = marked.read_bytes()
    assert _whiteout(env, scan_file, base_sha256=_sha(marked)).status_code == 409
    assert marked.read_bytes() == before


def test_whiteout_permissions(env, marked):
    db = env["db"]
    scan_file = env["files"]["01/1.pdf"]
    other = User(username="hc2", password="x", full_name="Người khác", role="user", account_type="staff")
    db.add(other)
    db.commit()
    _start_check_scan(env, user=other)
    before = marked.read_bytes()

    # Thành viên Check scan nhưng hộp đang do người khác check.
    res = _whiteout(env, scan_file, base_sha256=_sha(marked))
    assert res.status_code == 403
    assert client.get(_view_url(env)).json()["data"]["can_whiteout"] is False

    # Người scan xem được gói nhưng không được bôi.
    scanner = User(username="scan", password="x", full_name="Người scan", role="user", account_type="staff")
    db.add(scanner)
    db.commit()
    db.add(ProjectStageMember(project_id=env["project"].id, user_id=scanner.id, stage_key="scan"))
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as(scanner)
    assert client.get(_view_url(env)).status_code == 200
    assert _whiteout(env, scan_file, base_sha256=_sha(marked)).status_code == 403

    # CTV dù là thành viên Check scan cũng không được.
    db.add(ProjectStageMember(project_id=env["project"].id, user_id=env["ctv"].id, stage_key="scan_qc"))
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as(env["ctv"])
    assert _whiteout(env, scan_file, base_sha256=_sha(marked)).status_code == 403
    assert marked.read_bytes() == before

    # Admin được bôi khi Check scan đang làm, kể cả hộp do người khác nhận.
    app.dependency_overrides[get_current_user] = lambda: _as(env["admin"])
    assert _whiteout(env, scan_file, base_sha256=_sha(marked)).status_code == 200
    assert marked.read_bytes() != before


def test_whiteout_only_on_latest_package(env, marked):
    _start_check_scan(env)
    db = env["db"]
    db.add(CaseScanPackage(case_id=env["case"].id, version=2, source_path="P1/Hộp 01",
                           status="done", submitted_by_user_id=env["admin"].id))
    db.commit()
    res = _whiteout(env, env["files"]["01/1.pdf"], base_sha256=_sha(marked))
    assert res.status_code == 409
    assert "mới nhất" in res.json()["detail"]


@pytest.mark.parametrize("body,status", [
    ({"page": 0}, 400),
    ({"page": 3}, 400),
    ({"page": "1"}, 400),
    ({"page": True}, 400),
    ({"strokes": []}, 400),
    ({"strokes": [{"width": 0.03, "points": []}]}, 400),
    ({"strokes": [{"width": 0.03, "points": [[1.5, 0.1]]}]}, 400),
    ({"strokes": [{"width": 0.5, "points": [[0.1, 0.1]]}]}, 400),
    ({"strokes": [{"width": 0.03, "points": [[0.1]]}]}, 400),
    ({"strokes": [{"width": 0.03, "points": [[0.1, 0.1]]}] * 301}, 400),
    ({"extra": 1}, 422),
])
def test_whiteout_validates_input(env, marked, body, status):
    _start_check_scan(env)
    before = marked.read_bytes()
    res = _whiteout(env, env["files"]["01/1.pdf"], base_sha256=_sha(marked), **body)
    assert res.status_code == status, res.text
    assert marked.read_bytes() == before


def test_whiteout_blocked_after_handover_lock(env, marked):
    _start_check_scan(env)
    before = marked.read_bytes()
    env["project"].handover_locked_at = datetime(2026, 11, 1)
    env["db"].commit()
    res = _whiteout(env, env["files"]["01/1.pdf"], base_sha256=_sha(marked))
    assert res.status_code == 423
    assert marked.read_bytes() == before


def test_whiteout_replace_failure_keeps_original(env, marked, monkeypatch):
    _start_check_scan(env)
    before = marked.read_bytes()

    def refuse(*_args):
        raise PermissionError("file đang mở")

    monkeypatch.setattr(scan_check_service.os, "replace", refuse)
    res = _whiteout(env, env["files"]["01/1.pdf"], base_sha256=_sha(marked))
    assert res.status_code == 409
    assert marked.read_bytes() == before
    assert not any(p.name.endswith(".docops-tmp") for p in marked.parent.iterdir())
    env["db"].refresh(env["files"]["01/1.pdf"])
    assert env["files"]["01/1.pdf"].sha256 is None
