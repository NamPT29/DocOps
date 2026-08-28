import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    Project,
    ProjectAssignmentHistory,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Template,
    User,
)
from server.services.project_assignment_service import assign_unassigned_project_cases


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-assignment.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def seed_assignment_project(database, *, case_count=4):
    admin = User(username="assignment-admin", password="hash", role="admin")
    first = User(username="assignment-first", password="hash", role="user")
    second = User(username="assignment-second", password="hash", role="user")
    reviewer = User(username="assignment-reviewer", password="hash", role="user")
    template = Template(name="Assignment form", filename="assignment.xlsm")
    database.add_all([admin, first, second, reviewer, template])
    database.flush()
    project = Project(
        name="Assignment project",
        root_folder_name="assignment-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode="pdf",
        created_by_user_id=admin.id,
    )
    database.add(project)
    database.flush()
    cases = [
        ProjectCase(
            project_id=project.id,
            case_key=f"{index:03d}",
            display_name=f"{index:03d}",
        )
        for index in range(1, case_count + 1)
    ]
    database.add_all(cases)
    database.flush()
    return admin, first, second, reviewer, project, cases


def add_case_assets(database, project, cases, pdf_counts):
    for case_row, pdf_count in zip(cases, pdf_counts):
        report = ProjectReportUnit(
            project_id=project.id,
            case_id=case_row.id,
            report_key=f"{case_row.case_key}/report",
            display_name=f"Report {case_row.case_key}",
        )
        database.add(report)
        database.flush()
        for index in range(pdf_count):
            relative_path = f"{case_row.case_key}/{index + 1}.pdf"
            database.add(
                ProjectDocumentAsset(
                    project_id=project.id,
                    case_id=case_row.id,
                    report_unit_id=report.id,
                    relative_path=relative_path,
                    normalized_relative_path=relative_path.casefold(),
                    original_filename=f"{index + 1}.pdf",
                    storage_filename=f"case-{case_row.id}-{index + 1}.pdf",
                    content_sha256=f"{case_row.id:08x}{index + 1:056x}",
                    byte_size=100 + index,
                    status="active",
                )
            )
    database.flush()


def test_assignment_balances_whole_cases_and_prevents_self_review(database):
    admin, first, second, reviewer, project, cases = seed_assignment_project(database)
    database.add_all(
        [
            ProjectMember(project_id=project.id, user_id=first.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=second.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=first.id, member_role="reviewer"),
            ProjectMember(project_id=project.id, user_id=second.id, member_role="reviewer"),
            ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="reviewer"),
        ]
    )
    database.flush()

    result = assign_unassigned_project_cases(
        database,
        project_id=project.id,
        changed_by_user_id=admin.id,
    )
    database.commit()

    assert result == {"input_assigned": 4, "reviewer_assigned": 4}
    assert all(case.assigned_input_user_id != case.assigned_reviewer_user_id for case in cases)
    input_counts = {
        user_id: sum(case.assigned_input_user_id == user_id for case in cases)
        for user_id in (first.id, second.id)
    }
    assert sorted(input_counts.values()) == [2, 2]
    assert database.query(ProjectAssignmentHistory).count() == 8


def test_assignment_balances_pdf_weight_instead_of_case_count(database):
    admin, first, second, reviewer, project, cases = seed_assignment_project(database)
    pdf_counts = [1, 9, 8, 2]
    add_case_assets(database, project, cases, pdf_counts)
    database.add_all(
        [
            ProjectMember(project_id=project.id, user_id=first.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=second.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=first.id, member_role="reviewer"),
            ProjectMember(project_id=project.id, user_id=second.id, member_role="reviewer"),
            ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="reviewer"),
        ]
    )
    database.flush()

    result = assign_unassigned_project_cases(
        database,
        project_id=project.id,
        changed_by_user_id=admin.id,
    )

    input_pdf_loads = {
        user_id: sum(
            pdf_count
            for case_row, pdf_count in zip(cases, pdf_counts)
            if case_row.assigned_input_user_id == user_id
        )
        for user_id in (first.id, second.id)
    }
    assert result == {"input_assigned": 4, "reviewer_assigned": 4}
    assert input_pdf_loads == {first.id: 10, second.id: 10}
    assert all(case.assigned_input_user_id != case.assigned_reviewer_user_id for case in cases)


def test_assignment_leaves_reviewer_empty_when_only_self_is_available(database):
    admin, first, _, _, project, cases = seed_assignment_project(database, case_count=2)
    database.add_all(
        [
            ProjectMember(project_id=project.id, user_id=first.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=first.id, member_role="reviewer"),
        ]
    )
    database.flush()

    result = assign_unassigned_project_cases(
        database,
        project_id=project.id,
        changed_by_user_id=admin.id,
    )

    assert result == {"input_assigned": 2, "reviewer_assigned": 0}
    assert all(case.assigned_input_user_id == first.id for case in cases)
    assert all(case.assigned_reviewer_user_id is None for case in cases)


def test_assignment_preserves_existing_case_owner(database):
    admin, first, second, reviewer, project, cases = seed_assignment_project(database, case_count=2)
    cases[0].assigned_input_user_id = second.id
    cases[0].assigned_reviewer_user_id = reviewer.id
    database.add_all(
        [
            ProjectMember(project_id=project.id, user_id=first.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=second.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="reviewer"),
        ]
    )
    database.flush()

    assign_unassigned_project_cases(
        database,
        project_id=project.id,
        changed_by_user_id=admin.id,
    )

    assert cases[0].assigned_input_user_id == second.id
    assert cases[0].assigned_reviewer_user_id == reviewer.id
