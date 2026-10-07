import json
import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from server.models import (
    Project,
    ProjectCase,
    Submission,
)
from server.models_entry_qc import (
    CaseEntryQcSampleItem,
    CaseEntryQcSampling,
    CaseEntryQcResult,
)
from server.repositories.project_admin_repository import ProjectAdminRepository

@pytest.fixture(scope="function")
def engine_with_fks(tmp_path):
    from sqlalchemy import create_engine
    db_path = tmp_path / "test_fks.db"
    engine = create_engine(f"sqlite:///{db_path}")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    return engine

@pytest.fixture(scope="function")
def fk_db(engine_with_fks):
    from alembic.config import Config
    from alembic import command
    from server.database import SessionLocal

    # Setup schema
    alembic_cfg = Config("alembic.ini")
    with engine_with_fks.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    # Override SessionLocal to use our engine
    Session = type(SessionLocal)(bind=engine_with_fks)
    db = Session()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        engine_with_fks.dispose()

@pytest.fixture
def client():
    from server.main import app
    yield TestClient(app)

@pytest.fixture(scope="function")
def fk_client(fk_db, client):
    from server.database import get_db
    client.app.dependency_overrides[get_db] = lambda: fk_db
    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_db, None)

def setup_fk_mock_data(db):
    admin = User(username="admin", full_name="Admin", role="admin", password="")
    p1 = Project(name="Project 1", root_folder_name="P1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    db.add(admin)
    db.add(p1)
    db.commit()
    c1 = ProjectCase(project_id=p1.id, case_key="Case1", display_name="Case 1")
    db.add(c1)
    db.commit()
    from tests.test_entry_qc_round2 import setup_headers
    return {"admin": admin, "p1": p1, "c1": c1}

def test_delete_project_with_round2_sample(fk_client, fk_db):
    from server.models import User, Template
    admin = User(username="admin", full_name="Admin", role="admin", password="")
    t1 = Template(name="T1", filename="t1")
    fk_db.add(admin)
    fk_db.add(t1)
    fk_db.commit()
    p1 = Project(name="Project 1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    fk_db.add(p1)
    fk_db.commit()
    c1 = ProjectCase(project_id=p1.id, case_key="Case1", display_name="Case 1")
    fk_db.add(c1)
    fk_db.commit()
    from tests.test_entry_qc_round2 import setup_headers, make_submissions
    setup_headers(fk_client.app.dependency_overrides, {"id": admin.id, "username": admin.username, "role": admin.role})

    make_submissions(fk_db, p1.id, c1.id, admin.id, 1)
    fk_db.add(CaseEntryQcResult(project_id=p1.id, case_id=c1.id, round=1, reports_total=1, reports_assessed=1, error_reports=0, total_fields=1, error_fields=0, rate_percent=0, threshold_percent=5, passed=True, created_by_user_id=admin.id))
    fk_db.commit()
    
    # Take sample
    fk_client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    r = fk_client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc").json()
    sub_id = r["data"]["round2"]["sampling"]["items"][0]["submission_id"]
    
    # Check item manually in DB
    item = fk_db.query(CaseEntryQcSampleItem).filter_by(submission_id=sub_id).first()
    item.final_data_json = "{}"
    fk_db.commit()

    # Delete project
    res = fk_client.delete(f"/api/projects/{p1.id}")
    assert res.status_code == 200

    assert fk_db.query(CaseEntryQcSampleItem).count() == 0
    assert fk_db.query(CaseEntryQcSampling).count() == 0
    assert fk_db.query(CaseEntryQcResult).count() == 0


def test_delete_submission_with_round2_sample(fk_client, fk_db):
    from server.models import User, Template
    admin = User(username="admin", full_name="Admin", role="admin", password="")
    t1 = Template(name="T1", filename="t1")
    fk_db.add(admin)
    fk_db.add(t1)
    fk_db.commit()
    p1 = Project(name="Project 1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    fk_db.add(p1)
    fk_db.commit()
    c1 = ProjectCase(project_id=p1.id, case_key="Case1", display_name="Case 1")
    fk_db.add(c1)
    fk_db.commit()
    from tests.test_entry_qc_round2 import setup_headers, make_submissions
    setup_headers(fk_client.app.dependency_overrides, {"id": admin.id, "username": admin.username, "role": admin.role})

    make_submissions(fk_db, p1.id, c1.id, admin.id, 1)
    fk_db.add(CaseEntryQcResult(project_id=p1.id, case_id=c1.id, round=1, reports_total=1, reports_assessed=1, error_reports=0, total_fields=1, error_fields=0, rate_percent=0, threshold_percent=5, passed=True, created_by_user_id=admin.id))
    fk_db.commit()
    
    fk_client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    r = fk_client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc").json()
    sub_id = r["data"]["round2"]["sampling"]["items"][0]["submission_id"]

    res = fk_client.delete(f"/api/submissions/{sub_id}")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_sampled"

    assert fk_db.get(Submission, sub_id) is not None

def test_delete_submission_without_round2_sample(fk_client, fk_db):
    from server.models import User, Template
    admin = User(username="admin", full_name="Admin", role="admin", password="")
    t1 = Template(name="T1", filename="t1")
    fk_db.add(admin)
    fk_db.add(t1)
    fk_db.commit()
    p1 = Project(name="Project 1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    fk_db.add(p1)
    fk_db.commit()
    c1 = ProjectCase(project_id=p1.id, case_key="Case1", display_name="Case 1")
    fk_db.add(c1)
    fk_db.commit()
    from tests.test_entry_qc_round2 import setup_headers, make_submissions
    setup_headers(fk_client.app.dependency_overrides, {"id": admin.id, "username": admin.username, "role": admin.role})

    make_submissions(fk_db, p1.id, c1.id, admin.id, 1)
    sub = fk_db.query(Submission).first()
    sub_id = sub.id

    res = fk_client.delete(f"/api/submissions/{sub_id}")
    assert res.status_code == 200

    assert fk_db.get(Submission, sub_id) is None

def test_pragma_foreign_keys_on(fk_db):
    from server.models import User, Template
    admin = User(username="admin", full_name="Admin", role="admin", password="")
    t1 = Template(name="T1", filename="t1")
    fk_db.add(admin)
    fk_db.add(t1)
    fk_db.commit()
    p1 = Project(name="Project 1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    fk_db.add(p1)
    fk_db.commit()
    c1 = ProjectCase(project_id=p1.id, case_key="Case1", display_name="Case 1")
    fk_db.add(c1)
    fk_db.commit()
    from tests.test_entry_qc_round2 import make_submissions
    make_submissions(fk_db, p1.id, c1.id, admin.id, 1)
    sub_id = fk_db.query(Submission).first().id

    fk_db.add(CaseEntryQcSampling(
        project_id=p1.id, 
        case_id=c1.id, 
        round=2, 
        population_count=1, 
        sample_size=1, 
        sample_rate_percent=100.0, 
        seed=123, 
        created_by_user_id=admin.id
    ))
    fk_db.commit()

    sampling = fk_db.query(CaseEntryQcSampling).first()

    fk_db.add(CaseEntryQcSampleItem(sampling_id=sampling.id, submission_id=sub_id, baseline_data_json="{}"))
    fk_db.commit()

    with pytest.raises(IntegrityError):
        from sqlalchemy import text
        fk_db.execute(text(f"DELETE FROM submissions WHERE id = {sub_id}"))
