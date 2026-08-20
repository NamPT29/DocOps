import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    ProjectUploadFile,
    ProjectUploadSession,
    Template,
    User,
)


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-models.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def create_project_graph(database, *, report_mode="folder_level"):
    admin = User(username="project-admin", password="hash", role="admin")
    worker = User(username="project-worker", password="hash", role="user")
    template = Template(name="Project template", filename="project.xlsm")
    database.add_all([admin, worker, template])
    database.flush()

    project = Project(
        name="Project A",
        root_folder_name="project-a",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode=report_mode,
        report_level=2 if report_mode == "folder_level" else None,
        created_by_user_id=admin.id,
    )
    database.add(project)
    database.flush()

    case = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=worker.id,
    )
    database.add(case)
    database.flush()

    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case.id,
        report_key="001/report-01",
        display_name="report-01",
    )
    database.add(report)
    database.flush()
    return admin, worker, project, case, report


def test_project_allows_empty_member_pools_and_pins_template_snapshot(database):
    admin, _, project, _, _ = create_project_graph(database)
    database.commit()

    stored = database.get(Project, project.id)
    assert stored.created_by_user_id == admin.id
    assert stored.template_name_snapshot == "Project template"
    assert stored.template_filename_snapshot == "project.xlsm"
    assert database.query(ProjectMember).filter_by(project_id=project.id).count() == 0


def test_user_can_hold_input_and_reviewer_roles_in_same_project(database):
    _, worker, project, _, _ = create_project_graph(database)
    database.add_all(
        [
            ProjectMember(project_id=project.id, user_id=worker.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=worker.id, member_role="reviewer"),
        ]
    )
    database.commit()

    roles = {
        row.member_role
        for row in database.query(ProjectMember).filter_by(
            project_id=project.id,
            user_id=worker.id,
        )
    }
    assert roles == {"input", "reviewer"}


def test_report_accepts_multiple_pdfs_but_rejects_exact_duplicate_identity(database):
    _, _, project, case, report = create_project_graph(database)
    first = ProjectDocumentAsset(
        project_id=project.id,
        case_id=case.id,
        report_unit_id=report.id,
        relative_path="001/report-01/page-1.pdf",
        normalized_relative_path="001/report-01/page-1.pdf",
        original_filename="page-1.pdf",
        storage_filename="asset-one.pdf",
        content_sha256="a" * 64,
        byte_size=100,
    )
    second = ProjectDocumentAsset(
        project_id=project.id,
        case_id=case.id,
        report_unit_id=report.id,
        relative_path="001/report-01/page-2.pdf",
        normalized_relative_path="001/report-01/page-2.pdf",
        original_filename="page-2.pdf",
        storage_filename="asset-two.pdf",
        content_sha256="b" * 64,
        byte_size=200,
    )
    database.add_all([first, second])
    database.commit()

    assert database.query(ProjectDocumentAsset).filter_by(report_unit_id=report.id).count() == 2

    duplicate = ProjectDocumentAsset(
        project_id=project.id,
        case_id=case.id,
        report_unit_id=report.id,
        relative_path=first.relative_path,
        normalized_relative_path=first.normalized_relative_path,
        original_filename=first.original_filename,
        storage_filename="asset-duplicate.pdf",
        content_sha256=first.content_sha256,
        byte_size=first.byte_size,
    )
    database.add(duplicate)
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_upload_session_is_idempotent_and_tracks_resume_offset(database):
    admin, _, project, _, _ = create_project_graph(database, report_mode="pdf")
    session = ProjectUploadSession(
        id="upload-session-1",
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="browser-key-1",
        manifest_digest="c" * 64,
        total_files=1,
        requested_files=1,
    )
    database.add(session)
    database.flush()
    upload_file = ProjectUploadFile(
        session_id=session.id,
        relative_path="001/report.pdf",
        normalized_relative_path="001/report.pdf",
        expected_sha256="d" * 64,
        expected_size=32,
        next_offset=16,
        staging_filename="upload-session-1.part",
    )
    database.add(upload_file)
    database.commit()

    stored = database.query(ProjectUploadFile).one()
    assert stored.next_offset == 16
    assert stored.expected_size == 32

    duplicate_session = ProjectUploadSession(
        id="upload-session-2",
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key=session.client_session_key,
        manifest_digest="e" * 64,
    )
    database.add(duplicate_session)
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()
