import json

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.routers.documents import (
    RedistributeFolderReviewersRequest,
    redistribute_folder_reviewers,
)
from server.services.project_workspace_service import sync_project_assets_to_documents
from server.utils.folder_utils import folder_path_key


def _select_count(engine, operation):
    statements = []

    def before_cursor_execute(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return len(statements), result


def _new_database(path):
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def _sync_selects(tmp_path, asset_count):
    engine, session_factory = _new_database(
        tmp_path / f"sync-{asset_count}.sqlite3",
    )
    seed = session_factory()
    admin = User(username=f"sync-admin-{asset_count}", password="hash", role="admin")
    input_user = User(username=f"sync-input-{asset_count}", password="hash", role="user")
    reviewer = User(username=f"sync-reviewer-{asset_count}", password="hash", role="user")
    template = Template(name="Query-count template", filename="query-count.xlsx")
    seed.add_all([admin, input_user, reviewer, template])
    seed.flush()
    project = Project(
        name="Query-count project",
        root_folder_name="query-count",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        template_config_json_snapshot="{}",
        form_schema_json_snapshot="[]",
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    seed.add(project)
    seed.flush()
    case = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=input_user.id,
        assigned_reviewer_user_id=reviewer.id,
    )
    seed.add(case)
    seed.flush()
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case.id,
        report_key="001/report",
        display_name="report",
    )
    seed.add(report)
    seed.flush()

    for index in range(asset_count):
        document = AssignedDocument(
            original_filename=f"report-{index}.pdf",
            uuid_filename=f"sync-{asset_count}-{index}.pdf",
            assigned_to_user_id=input_user.id,
            template_id=template.id,
            status="pending",
        )
        seed.add(document)
        seed.flush()
        seed.add_all([
            AssignedDocumentPath(
                document_id=document.id,
                relative_path=f"001/report-{index}.pdf",
                upload_id=f"existing-{asset_count}-{index}",
            ),
            AssignedDocumentFolder(
                document_id=document.id,
                folder_group="project/old/001",
            ),
            AssignedDocumentReviewAssignment(
                document_id=document.id,
                reviewer_user_id=reviewer.id,
            ),
            ProjectDocumentAsset(
                project_id=project.id,
                case_id=case.id,
                report_unit_id=report.id,
                assigned_document_id=document.id,
                relative_path=f"001/report-{index}.pdf",
                normalized_relative_path=f"001/report-{index}.pdf",
                original_filename=f"report-{index}.pdf",
                storage_filename=document.uuid_filename,
                content_sha256=f"{index:064x}",
                byte_size=100 + index,
                status="active",
            ),
        ])
    seed.commit()
    project_id = project.id
    seed.close()

    db = session_factory()
    try:
        select_count, result = _select_count(
            engine,
            lambda: sync_project_assets_to_documents(db, project_id=project_id),
        )
        assert result == {
            "created_documents": 0,
            "updated_documents": asset_count,
        }
        db.rollback()
        return select_count
    finally:
        db.close()
        engine.dispose()


def test_project_asset_sync_select_count_is_independent_of_asset_count(tmp_path):
    one_asset = _sync_selects(tmp_path, 1)
    many_assets = _sync_selects(tmp_path, 25)

    assert many_assets == one_asset
    assert many_assets <= 8


def _redistribution_selects(tmp_path, assignment_count):
    engine, session_factory = _new_database(
        tmp_path / f"redistribute-{assignment_count}.sqlite3",
    )
    seed = session_factory()
    admin = User(username=f"redistribute-admin-{assignment_count}", password="hash", role="admin")
    input_user = User(username=f"redistribute-input-{assignment_count}", password="hash", role="user")
    old_reviewer = User(username=f"redistribute-old-{assignment_count}", password="hash", role="user")
    new_reviewer = User(username=f"redistribute-new-{assignment_count}", password="hash", role="user")
    seed.add_all([admin, input_user, old_reviewer, new_reviewer])
    seed.flush()
    admin_id = admin.id
    new_reviewer_id = new_reviewer.id

    for index in range(assignment_count):
        document = AssignedDocument(
            original_filename=f"redistribute-{index}.pdf",
            uuid_filename=f"redistribute-{assignment_count}-{index}.pdf",
            assigned_to_user_id=input_user.id,
            status="completed",
        )
        seed.add(document)
        seed.flush()
        submission = Submission(
            data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
            created_by_user_id=input_user.id,
            assigned_document_id=document.id,
            folder_path="query-count-folder",
            folder_path_key=folder_path_key("query-count-folder"),
            status="pending_review",
        )
        seed.add(submission)
        seed.flush()
        seed.add_all([
            AssignedDocumentFolder(
                document_id=document.id,
                folder_group="query-count-folder",
            ),
            AssignedDocumentReviewAssignment(
                document_id=document.id,
                reviewer_user_id=old_reviewer.id,
            ),
            SubmissionReviewAssignment(
                submission_id=submission.id,
                reviewer_user_id=old_reviewer.id,
            ),
        ])
    seed.commit()
    seed.close()

    db = session_factory()
    try:
        select_count, result = _select_count(
            engine,
            lambda: redistribute_folder_reviewers(
                RedistributeFolderReviewersRequest(
                    reviewer_user_ids=[new_reviewer_id],
                ),
                current_user={
                    "id": admin_id,
                    "username": f"redistribute-admin-{assignment_count}",
                    "role": "admin",
                },
                db=db,
            ),
        )
        assert result["document_updates"] == assignment_count
        assert result["submission_updates"] == assignment_count
        return select_count
    finally:
        db.close()
        engine.dispose()


def test_reviewer_redistribution_select_count_is_independent_of_assignment_count(
    tmp_path,
):
    one_assignment = _redistribution_selects(tmp_path, 1)
    many_assignments = _redistribution_selects(tmp_path, 25)

    assert many_assignments == one_assignment
    assert many_assignments <= 8
