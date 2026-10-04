"""FR-ARR-01: arrangement catalogue import (QC-16, QC-05, QC-07, QC-13)."""

import io
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    ArrangementDossier,
    ArrangementImport,
    CaseStageState,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Template,
    User,
)
from server.repositories.project_upload_repository import ProjectUploadRepository
from server.routers import arrangement as arrangement_router
from server.services import arrangement_catalog_parser as parser
from server.services import arrangement_catalog_service as catalog
from server.services import project_upload_service, workflow_service
from server.services.project_assignment_service import assign_unassigned_project_cases
from server.services.project_manifest_service import derive_project_group_keys

TODAY = date(2026, 10, 4)
HEADER = [
    "STT", "Mã phông (*)", "Tên phông (*)", "Mục lục số (*)", "Hộp số (*)", "Hồ sơ số (*)",
    "Ký hiệu hồ sơ", "Tiêu đề hồ sơ (*)", "Thời gian bắt đầu (*)", "Thời gian kết thúc (*)",
    "Thời hạn bảo quản (*)", "Số tờ (*)", "Giai đoạn/Nhiệm kỳ", "Giấy xấu", "Ghi chú",
]
KEYS = [
    "stt", "fonds_code", "fonds_name", "catalog_number", "box", "dossier", "notation", "title",
    "start", "end", "thbq", "sheets", "term", "bad", "note",
]


def dossier(box, number, **overrides):
    row = {
        "fonds_code": "01", "fonds_name": "Phông mẫu", "catalog_number": "1",
        "box": box, "dossier": number, "title": f"Hồ sơ {number} (dữ liệu giả)",
        "start": "05/01/2020", "end": "28/12/2020", "thbq": "01", "sheets": 10,
    }
    row.update(overrides)
    return row


def workbook_bytes(rows, *, header=HEADER, sheet="Muc_luc", blank_rows=()):
    book = Workbook()
    ws = book.active
    ws.title = sheet
    ws.append(header)
    for index, row in enumerate(rows):
        if index in blank_rows:
            ws.append([])
        ws.append([row.get(key) for key in KEYS])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def parse(rows, **kwargs):
    return parser.parse_catalog_workbook(workbook_bytes(rows, **kwargs), today=TODAY)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'catalog.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db):
    admin = User(username="pm", password="x", role="admin")
    staff = User(username="nv1", password="x", role="user")
    template = Template(name="t", filename="t.xlsx", is_active=True)
    db.add_all([admin, staff, template])
    db.flush()
    project = Project(
        name="Bộ Y tế", root_folder_name="phong01", template_id=template.id,
        template_name_snapshot="t", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=admin.id,
    )
    db.add(project)
    db.commit()
    return SimpleNamespace(db=db, admin=admin, staff=staff, project=project)


def preview(world, rows):
    return catalog.preview_catalog(
        world.db, project_id=world.project.id, file_name="muc_luc.xlsx",
        content=workbook_bytes(rows), today=TODAY,
    )


def apply(world, rows, token=None):
    content = workbook_bytes(rows)
    if token is None:
        token = catalog.preview_catalog(
            world.db, project_id=world.project.id, file_name="muc_luc.xlsx",
            content=content, today=TODAY,
        )["plan_token"]
    return catalog.import_catalog(
        world.db, project_id=world.project.id, file_name="muc_luc.xlsx", content=content,
        plan_token=token, actor_user_id=world.admin.id, today=TODAY,
    )


def add_pdf(world, relative_path):
    project = world.project
    grouping = derive_project_group_keys(
        relative_path, case_level=project.case_level,
        report_mode=project.report_mode, report_level=project.report_level,
    )
    case_row = world.db.query(ProjectCase).filter_by(
        project_id=project.id, case_key=grouping["case_key"]
    ).first()
    if case_row is None:
        case_row = ProjectCase(
            project_id=project.id, case_key=grouping["case_key"], display_name=grouping["case_name"],
        )
        world.db.add(case_row)
        world.db.flush()
    report = ProjectReportUnit(
        project_id=project.id, case_id=case_row.id,
        report_key=grouping["report_key"], display_name=grouping["report_name"],
    )
    world.db.add(report)
    world.db.flush()
    world.db.add(ProjectDocumentAsset(
        project_id=project.id, case_id=case_row.id, report_unit_id=report.id,
        relative_path=relative_path, normalized_relative_path=relative_path.casefold(),
        original_filename=relative_path.rsplit("/", 1)[-1],
        storage_filename=f"{uuid.uuid4().hex}.pdf", content_sha256="0" * 64, byte_size=1,
        status="active",
    ))
    world.db.commit()
    return case_row


# --- parsing ----------------------------------------------------------------


def test_rows_are_read_by_header_text_in_any_order():
    reordered = list(reversed(HEADER))
    book = Workbook()
    ws = book.active
    ws.title = "muc_luc"
    ws.append([text.lower() for text in reordered])
    values = dossier(
        "0020", "12B", start=datetime(2019, 6, 15), end="5/1/2020", thbq=1,
        sheets=120.0, bad="X", notation="HC",
    )
    ws.append([values.get(key) for key in reversed(KEYS)])
    buffer = io.BytesIO()
    book.save(buffer)

    parsed = parser.parse_catalog_workbook(buffer.getvalue(), today=TODAY)

    assert parsed.errors == [] and parsed.file_errors == []
    row = parsed.rows[0]
    assert (row.row, row.box_number, row.dossier_number, row.dossier_suffix) == (2, 20, 12, "b")
    assert row.values["start_date"] == "15/06/2019"
    assert row.values["end_date"] == "05/01/2020"
    assert row.values["start_year"] == 2019
    assert row.values["maintenance_code"] == "01"
    assert row.values["sheet_count"] == 120
    assert row.values["bad_paper"] is True
    assert row.values["file_notation"] == "HC"


def test_partial_dates_follow_qc05():
    parsed = parse([
        dossier(1, 1, start="00/03/2020", end="00/00/2020"),
        dossier(1, 2, start="15/05/2020", end="00/00/2020"),  # end = some day in 2020
        dossier(1, 3, start="00/00/2021", end="31/12/2020"),
    ])
    assert [row.values["start_date"] for row in parsed.rows] == ["00/03/2020", "15/05/2020"]
    assert parsed.errors == [{
        "row": 4, "column": "Thời gian bắt đầu", "message": "Thời gian bắt đầu sau thời gian kết thúc.",
    }]


@pytest.mark.parametrize(
    ("overrides", "column", "message"),
    [
        ({"start": "31/02/2020"}, "Thời gian bắt đầu", "không tồn tại"),
        ({"start": "05/00/2020"}, "Thời gian bắt đầu", "00/00/yyyy"),
        ({"end": "01/13/2020"}, "Thời gian kết thúc", "Tháng"),
        ({"start": "01/01/1900"}, "Thời gian bắt đầu", "từ 1945"),
        ({"end": "01/01/2030"}, "Thời gian kết thúc", "đến 2026"),
        ({"start": 43831}, "Thời gian bắt đầu", "dd/mm/yyyy"),
        ({"start": "2020-01-05"}, "Thời gian bắt đầu", "dd/mm/yyyy"),
        ({"dossier": "12ab"}, "Hồ sơ số", "1 chữ cái"),
        ({"dossier": "a12"}, "Hồ sơ số", "1 chữ cái"),
        ({"dossier": "0"}, "Hồ sơ số", "1 chữ cái"),
        ({"box": "20a"}, "Hộp số", "số nguyên dương"),
        ({"thbq": "03"}, "Thời hạn bảo quản", "QC-13"),
        ({"sheets": 0}, "Số tờ", "số nguyên dương"),
        ({"bad": "có"}, "Giấy xấu", "chỉ ghi x"),
        ({"title": "  "}, "Tiêu đề hồ sơ", "bắt buộc"),
        ({"notation": "H.C"}, "Ký hiệu hồ sơ", "không dấu"),
    ],
)
def test_each_error_names_the_excel_row_and_column(overrides, column, message):
    overrides = dict(overrides)
    box = overrides.pop("box", 1)
    parsed = parse([dossier(1, 1), dossier(box, 2, **overrides)])
    assert len(parsed.rows) == 1
    assert len(parsed.errors) == 1
    error = parsed.errors[0]
    assert (error["row"], error["column"]) == (3, column)
    assert message in error["message"]


def test_duplicates_ignore_suffix_case_and_leading_zeros():
    parsed = parse([dossier(20, "12a"), dossier("0020", "012A")])
    assert parsed.errors[0]["row"] == 3
    assert "với dòng 2" in parsed.errors[0]["message"]


def test_blank_rows_are_skipped_but_row_numbers_stay_true():
    parsed = parse([dossier(1, 1), dossier(1, 2, sheets=0)], blank_rows=(1,))
    assert parsed.data_rows == 2
    assert parsed.errors[0]["row"] == 4


def test_file_level_problems(monkeypatch):
    assert "Thiếu cột bắt buộc: Số tờ" in parse([dossier(1, 1)], header=HEADER[:11]).file_errors[0]
    assert "Muc_luc" in parse([dossier(1, 1)], sheet="Sheet1").file_errors[0]
    assert ".xlsx" in parser.parse_catalog_workbook(b"STT;Hop", today=TODAY).file_errors[0]
    assert "chưa có hồ sơ" in parse([]).file_errors[0]
    monkeypatch.setattr(parser, "MAX_CATALOG_ROWS", 2)
    too_many = parse([dossier(1, 1), dossier(1, 2), dossier(1, 3)])
    assert "hơn 2 hồ sơ" in too_many.file_errors[0] and too_many.rows == []


def test_upload_size_and_type_are_checked_before_parsing(monkeypatch):
    def upload(name, size):
        return SimpleNamespace(filename=name, file=io.BytesIO(b"PK" + b"0" * size))

    with pytest.raises(HTTPException) as wrong_type:
        arrangement_router._read_catalog_file(upload("muc_luc.xls", 10))
    assert wrong_type.value.status_code == 400
    monkeypatch.setattr(arrangement_router, "MAX_CATALOG_BYTES", 100)
    with pytest.raises(HTTPException) as too_big:
        arrangement_router._read_catalog_file(upload("muc_luc.xlsx", 200))
    assert too_big.value.status_code == 413


# --- preview and import -------------------------------------------------------


def test_import_works_before_any_pdf_and_creates_boxes_awaiting_scan(world):
    rows = [dossier(1, 1), dossier(1, 2, bad="x"), dossier(2, 3)]
    result = preview(world, rows)
    assert result["can_import"] is True
    assert result["summary"] == {
        "added": 3, "updated": 0, "unchanged": 0, "removed": 0, "kept": 0, "new_boxes": 2,
    }
    assert world.db.query(ArrangementDossier).count() == 0, "preview writes nothing"

    apply(world, rows)

    boxes = {case.case_key: case.display_name for case in world.db.query(ProjectCase)}
    assert boxes == {"::muc-luc/hop-1": "Hộp 1", "::muc-luc/hop-2": "Hộp 2"}
    data = catalog.get_catalog(world.db, project_id=world.project.id)
    assert [(b["box_number"], b["dossier_count"], b["bad_paper_proposed"], b["awaiting_scan"])
            for b in data["boxes"]] == [(1, 2, True, True), (2, 1, False, True)]
    assert data["imports"][0]["imported_by"] == "pm"
    assert data["imports"][0]["added"] == 3


def test_any_error_blocks_the_whole_import(world):
    rows = [dossier(1, 1), dossier(1, 2, start="99/99/2020")]
    result = preview(world, rows)
    assert result["can_import"] is False and result["summary"] is None
    assert result["error_count"] == 1
    with pytest.raises(HTTPException) as blocked:
        apply(world, rows, token="anything")
    assert blocked.value.status_code == 400
    assert world.db.query(ArrangementDossier).count() == 0


def test_confirm_needs_the_previewed_state(world):
    rows = [dossier(1, 1)]
    token = preview(world, rows)["plan_token"]
    apply(world, [dossier(1, 1), dossier(1, 2)])  # someone imports meanwhile
    with pytest.raises(HTTPException) as stale:
        apply(world, rows, token=token)
    assert stale.value.status_code == 409


def test_reimport_updates_deletes_unscanned_and_keeps_scanned(world):
    apply(world, [dossier(1, 1), dossier(1, 2), dossier(1, 3), dossier(2, 4), dossier(9, 90)])
    box2 = world.db.query(ProjectCase).filter_by(case_key="::muc-luc/hop-2").one()
    world.db.add(CaseStageState(
        project_id=world.project.id, case_id=box2.id, stage_key="scan", status="in_progress",
    ))
    world.db.commit()

    new_file = [dossier(1, 1, title="Tiêu đề đã sửa"), dossier(1, 2), dossier(2, 5)]
    result = preview(world, new_file)
    assert result["summary"] == {
        "added": 1, "updated": 1, "unchanged": 1, "removed": 1, "kept": 1, "new_boxes": 0,
    }
    assert result["removed"] == [{"box": 1, "dossier": "3", "title": "Hồ sơ 3 (dữ liệu giả)"}]
    assert result["kept"][0]["dossier"] == "4"

    apply(world, new_file)

    keys = {(d.box_number, d.dossier_number) for d in world.db.query(ArrangementDossier)}
    assert keys == {(1, 1), (1, 2), (2, 4), (2, 5), (9, 90)}, "box 9 is not in the file: untouched"
    kept = world.db.query(ArrangementDossier).filter_by(box_number=2, dossier_number=4).one()
    assert kept.missing_from_import_id is not None
    box = {b["box_number"]: b for b in catalog.get_catalog(world.db, project_id=world.project.id)["boxes"]}
    assert box[2]["missing_count"] == 1 and box[2]["scan_started"] is True

    # Listing the row again clears the warning.
    apply(world, [dossier(2, 4), dossier(2, 5)])
    world.db.refresh(kept)
    assert kept.missing_from_import_id is None


def test_dossiers_sort_by_number_then_suffix(world):
    apply(world, [dossier(1, 13), dossier(1, "12a"), dossier(1, 12)])
    listing = catalog.get_box_dossiers(world.db, project_id=world.project.id, box_number=1)
    assert [item["dossier"] for item in listing] == ["12", "12a", "13"]


# --- folder levels: box = project case, dossier = the folder below -------------


def test_existing_box_folder_is_reused_by_number(world):
    case_row = add_pdf(world, "0020/0001/BIA.pdf")
    apply(world, [dossier(20, 1)])
    stored = world.db.query(ArrangementDossier).one()
    assert stored.case_id == case_row.id
    assert world.db.query(ProjectCase).count() == 1


def test_import_refuses_a_project_whose_case_level_is_the_dossier(world):
    add_pdf(world, "0020/BIA.pdf")  # PDFs right inside the case folder
    result = preview(world, [dossier(20, 1)])
    assert result["can_import"] is False
    assert "HỒ SƠ chứ không phải HỘP" in result["file_errors"][0]


def test_upload_attaches_a_box_folder_to_the_box_awaiting_scan(world):
    apply(world, [dossier(20, 1)])
    awaiting = world.db.query(ProjectCase).one()
    grouping = derive_project_group_keys(
        "0020/0001/BIA.pdf", case_level=1, report_mode="pdf", report_level=None,
    )

    case_row = project_upload_service._get_or_create_case(
        world.db, ProjectUploadRepository(world.db), world.project, grouping,
    )

    assert case_row.id == awaiting.id
    assert (case_row.case_key, case_row.display_name) == ("0020", "0020")
    assert world.db.query(ArrangementDossier).one().case_id == awaiting.id


@pytest.mark.parametrize(
    ("paths", "message"),
    [
        (["0020/BIA.pdf"], "HỒ SƠ chứ không phải HỘP"),
        (["01/0020/0001/BIA.pdf"], "PHÔNG"),
        (["hop20/0001/BIA.pdf"], "Hộp số"),
        (["0020/0001/BIA.pdf", "20/0002/BIA.pdf"], "nhiều thư mục"),
    ],
)
def test_upload_with_the_wrong_folder_level_is_refused(world, paths, message):
    apply(world, [dossier(20, 1)])
    with pytest.raises(HTTPException) as refused:
        catalog.require_catalog_upload_structure(world.db, world.project, paths)
    assert refused.value.status_code == 409
    assert message in refused.value.detail


def test_projects_without_a_catalogue_upload_as_before(world):
    catalog.require_catalog_upload_structure(world.db, world.project, ["anything/BIA.pdf"])


def test_boxes_awaiting_scan_are_not_handed_out_yet(world):
    world.db.add(ProjectMember(
        project_id=world.project.id, user_id=world.staff.id, member_role="input", is_active=True,
    ))
    world.db.commit()
    apply(world, [dossier(1, 1)])
    assign_unassigned_project_cases(
        world.db, project_id=world.project.id, changed_by_user_id=world.admin.id,
    )
    assert world.db.query(ProjectCase).one().assigned_input_user_id is None


# --- pipeline: Chỉnh lý completes only with a catalogue ----------------------


def test_arrangement_cannot_complete_without_the_box_catalogue(world):
    db, staff = world.db, world.staff
    apply(world, [dossier(20, 1)])
    with_catalog = db.query(ProjectCase).filter_by(case_key="::muc-luc/hop-20").one()
    workflow_service.configure_workflow(
        db, project_id=world.project.id, enabled_stage_keys=["arrangement", "scan"],
        members={"arrangement": [staff.id], "scan": [staff.id]}, actor_user_id=world.admin.id,
    )
    # Box 30 arrives after the pipeline was enabled, without a catalogue.
    no_catalog = add_pdf(world, "0030/0001/BIA.pdf")
    actor = {"id": staff.id, "username": staff.username, "role": "user"}

    def move(case_row, action):
        return workflow_service.transition_case_stage(
            db, project_id=world.project.id, case_id=case_row.id,
            stage_key="arrangement", action=action, actor=actor,
        )

    move(no_catalog, "start")
    with pytest.raises(HTTPException) as refused:
        move(no_catalog, "complete")
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "catalog_required"

    move(with_catalog, "start")
    move(with_catalog, "complete")
    assert db.query(CaseStageState).filter_by(
        case_id=with_catalog.id, stage_key="arrangement"
    ).one().status == "done"
    assert db.query(ArrangementImport).count() == 1
