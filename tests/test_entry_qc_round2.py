import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import uuid
import json

from server.database import Base, get_db
from server.main import app
from server.routers.auth import get_current_user, get_admin_user
from server.models import Project, User, ProjectCase, ProjectMember, ProjectReportUnit, AssignedDocument, ProjectDocumentAsset, Submission, ProjectPolicy, Template
from server.models_entry_qc import CaseEntryQcResult, CaseEntryQcSampling, CaseEntryQcSampleItem


def override_get_current_user(user):
    return lambda: user

def override_get_admin_user(user):
    def dep():
        if user["role"] != "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Yêu cầu quyền quản trị")
        return user
    return dep

@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:", 
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    
@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def mock_data(test_db):
    admin = User(username="admin", role="admin", password="")
    reviewer = User(username="reviewer", role="user", password="")
    test_db.add_all([admin, reviewer])
    test_db.commit()
    
    t1 = Template(name="T1", filename="t1")
    test_db.add(t1)
    test_db.commit()
    
    p1 = Project(name="P1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    test_db.add(p1)
    test_db.commit()
    
    test_db.add(ProjectPolicy(project_id=p1.id, error_threshold_percent=5, sample_rate_percent=30, entry_qc_round2_enabled=True))
    test_db.add(ProjectMember(project_id=p1.id, user_id=reviewer.id, member_role="reviewer", is_active=True))
    
    c1 = ProjectCase(project_id=p1.id, case_key="box1", display_name="box1")
    test_db.add(c1)
    test_db.commit()

    # Pass round 1
    r1 = CaseEntryQcResult(
        project_id=p1.id,
        case_id=c1.id,
        round=1,
        reports_total=10,
        reports_assessed=10,
        error_reports=0,
        total_fields=100,
        error_fields=0,
        rate_percent=0,
        threshold_percent=5,
        passed=True,
        created_by_user_id=admin.id
    )
    test_db.add(r1)
    test_db.commit()
    
    return {
        "admin": {"id": admin.id, "username": "admin", "role": "admin"},
        "reviewer": {"id": reviewer.id, "username": "reviewer", "role": "user"},
        "p1": p1,
        "c1": c1,
    }

def setup_headers(app_overrides, user):
    app_overrides[get_current_user] = override_get_current_user(user)
    app_overrides[get_admin_user] = override_get_admin_user(user)

def make_submissions(test_db, project_id, case_id, user_id, count, status="completed"):
    subs = []
    for i in range(count):
        r = ProjectReportUnit(project_id=project_id, case_id=case_id, report_key=f"r{i}", display_name=f"R{i}")
        test_db.add(r)
        test_db.flush()
        u = str(uuid.uuid4())
        a = AssignedDocument(original_filename="a", uuid_filename=u)
        test_db.add(a)
        test_db.flush()
        pa = ProjectDocumentAsset(project_id=project_id, case_id=case_id, report_unit_id=r.id, assigned_document_id=a.id, relative_path=f"a{i}", normalized_relative_path=f"a{i}", original_filename=f"a{i}", storage_filename=u, content_sha256=u, byte_size=1, status="pending")
        test_db.add(pa)
        test_db.flush()
        sub = Submission(assigned_document_id=a.id, data_json='{"field": "val"}', status=status, created_by_user_id=user_id)
        test_db.add(sub)
        test_db.flush()
        subs.append(sub)
    test_db.commit()
    return subs

def test_round2_sample_size(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    # N = 1 -> 30% -> ceil(0.3) -> 1
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 1)
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 200
    s = test_db.query(CaseEntryQcSampling).filter_by(case_id=mock_data["c1"].id).first()
    assert s.population_count == 1
    assert s.sample_size == 1

def test_round2_sample_size_3(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    # N = 3 -> 30% -> ceil(0.9) -> 1
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 3)
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 200
    s = test_db.query(CaseEntryQcSampling).filter_by(case_id=mock_data["c1"].id).first()
    assert s.population_count == 3
    assert s.sample_size == 1

def test_round2_sample_size_10(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    # N = 10 -> 30% -> ceil(3.0) -> 3
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 10)
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 200
    s = test_db.query(CaseEntryQcSampling).filter_by(case_id=mock_data["c1"].id).first()
    assert s.population_count == 10
    assert s.sample_size == 3

def test_round2_deterministic_seed(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    subs = make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 10)
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    s1 = test_db.query(CaseEntryQcSampling).filter_by(case_id=mock_data["c1"].id).first()
    items1 = [i.submission_id for i in test_db.query(CaseEntryQcSampleItem).all()]
    
    # re-run with same seed
    import random
    sorted_ids = sorted(s.id for s in subs)
    items2 = set(random.Random(s1.seed).sample(sorted_ids, s1.sample_size))
    
    assert set(items1) == set(items2)

def test_round2_policy_change_doesnt_affect_saved(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 10)
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    
    policy = test_db.query(ProjectPolicy).first()
    policy.sample_rate_percent = 50
    test_db.commit()
    
    s = test_db.query(CaseEntryQcSampling).filter_by(case_id=mock_data["c1"].id).first()
    assert float(s.sample_rate_percent) == 30.0

def test_round2_errors(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    
    # no_submissions
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "no_submissions"
    
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 2)
    
    # round2_disabled
    policy = test_db.query(ProjectPolicy).first()
    policy.entry_qc_round2_enabled = False
    test_db.commit()
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "round2_disabled"
    policy.entry_qc_round2_enabled = True
    test_db.commit()
    
    # round1_not_passed (not approved)
    r1 = test_db.query(CaseEntryQcResult).first()
    r1.passed = False
    r1.resolution = None
    test_db.commit()
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "round1_not_passed"
    
    r1.passed = True
    test_db.commit()
    
    # already_sampled
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 200
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "already_sampled"

def test_round2_null_policy(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 2)
    policy = test_db.query(ProjectPolicy).first()
    policy.entry_qc_round2_enabled = None
    test_db.commit()
    
    # QC-01 default is True, so it should pass
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 200

def test_round2_get_payload(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 1)
    client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    
    res = client.get(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc")
    assert res.status_code == 200
    data = res.json()["data"]
    
    assert "round2" in data
    r2 = data["round2"]
    assert r2["enabled"] is True
    assert r2["sampling"] is not None
    assert r2["sampling"]["sample_rate_percent"] == 30.0
    assert r2["sampling"]["population_count"] == 1
    assert r2["sampling"]["sample_size"] == 1
    assert "baseline_data_json" not in json.dumps(r2)
    
    assert len(r2["sampling"]["items"]) == 1
    item = r2["sampling"]["items"][0]
    assert item["report_name"] == "R0"
    assert "baseline_data_json" not in item

def test_round2_race_condition(client, mock_data, test_db, monkeypatch):
    setup_headers(app.dependency_overrides, mock_data["admin"])
    make_submissions(test_db, mock_data["p1"].id, mock_data["c1"].id, mock_data["admin"]["id"], 1)
    
    client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    
    # Mock repo.get_sampling to return None, bypassing the first check
    from server.repositories.entry_qc_repository import EntryQcRepository
    monkeypatch.setattr(EntryQcRepository, "get_sampling", lambda self, case_id, round_num: None)
    
    # The second call should now trigger IntegrityError at db.flush()
    res = client.post(f"/api/projects/{mock_data['p1'].id}/workflow/cases/{mock_data['c1'].id}/entry-qc/round2/sample")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "already_sampled"
