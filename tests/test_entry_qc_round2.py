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

def test_round2_check_item_success(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1) # user 999
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    # Check item
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {'field': 'val2', 'new_field': 'val3', '_internal': 'ignored'}}
    )
    assert res.status_code == 200
    
    # Verify GET reflects changes
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    item = r['data']['round2']['sampling']['items'][0]
    assert item['checked'] is True
    assert item['checked_by_name'] == 'admin'
    assert item['visible_field_count'] == 2 # field, new_field
    assert item['changed_field_count'] == 2 # both changed from baseline
    
    # Verify submission data_json updated
    from server.models import Submission
    sub = test_db.query(Submission).get(sub_id)
    data = json.loads(sub.data_json)
    assert data['field'] == 'val2'
    assert data['new_field'] == 'val3'
    assert data.get('_internal') is None # not updated

def test_round2_check_self_review_input(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, mock_data['admin']['id'], 1)
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {}}
    )
    assert res.status_code == 409
    assert res.json()['detail']['code'] == 'self_review'

def test_round2_check_self_review_reviewer(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    subs = make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    from server.models import SubmissionQualityAssessment
    # Admin was the reviewer
    test_db.add(SubmissionQualityAssessment(submission_id=subs[0].id, input_user_id=999, reviewer_user_id=mock_data['admin']['id'], baseline_data_json='{}', visible_field_count=1, changed_field_count=0, is_error_report=False))
    test_db.commit()
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {}}
    )
    assert res.status_code == 409
    assert res.json()['detail']['code'] == 'self_review'

def test_round2_already_checked(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    client.put(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}', json={'data': {}})
    res = client.put(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}', json={'data': {}})
    assert res.status_code == 409
    assert res.json()['detail']['code'] == 'already_checked'

def test_round2_submission_changed(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    subs = make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    
    subs[0].status = 'pending_input_confirmation'
    test_db.commit()
    
    res = client.put(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{subs[0].id}', json={'data': {}})
    assert res.status_code == 409
    assert res.json()['detail']['code'] == 'submission_changed'

def test_round2_finalize_items_unchecked(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    
    res = client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2')
    assert res.status_code == 409
    assert res.json()['detail']['code'] == 'items_unchecked'

def test_round2_finalize_pass_fail_boundary(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    subs = make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    
    baseline_data = {f"f{i}": "v" for i in range(100)}
    subs[0].data_json = json.dumps(baseline_data)
    test_db.commit()
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    data = dict(baseline_data)
    for i in range(5):
        data[f"f{i}"] = "changed"
    
    client.put(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}', json={'data': data})
    
    res = client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2')
    assert res.status_code == 200
    assert res.json()['data']['passed'] is False
    assert res.json()['data']['rate_percent'] == 5.0
    
    # test resolve
    res = client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/resolve', json={"reason": "ok"})
    assert res.status_code == 200

def test_round2_finalize_threshold_change_no_affect(client, mock_data, test_db):
    setup_headers(app.dependency_overrides, mock_data['admin'])
    subs = make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    
    baseline_data = {f"f{i}": "v" for i in range(100)}
    subs[0].data_json = json.dumps(baseline_data)
    test_db.commit()
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    data = dict(baseline_data)
    for i in range(4):
        data[f"f{i}"] = "changed"
        
    client.put(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}', json={'data': data})
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2')
    
    # Change threshold to 2%
    from server.models import ProjectPolicy
    pol = test_db.query(ProjectPolicy).first()
    pol.error_threshold_percent = 2
    test_db.commit()
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    assert r['data']['rounds'][1]['passed'] is True # Still true!
    assert r['data']['rounds'][1]['threshold_percent'] == 5.0

def test_api_contract_round2_structure(client, test_db, mock_data):
    # This test ensures the returned API dictionary exactly matches the specified schema.
    admin = mock_data["admin"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    setup_headers(client.app.dependency_overrides, admin)

    # First, make submissions so we can sample
    subs = make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    
    # Enable round 2 and sample
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    # Check one item to populate checked_by_name, etc.
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    item = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).first()
    client.put(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{item.submission_id}", json={"data": {"field1": "val1"}})
    
    response = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert response.status_code == 200
    data = response.json()["data"]
    
    assert "round2" in data
    round2 = data["round2"]
    assert set(round2.keys()) == {"enabled", "sampling"}
    
    assert round2["sampling"] is not None
    sampling_data = round2["sampling"]
    
    expected_sampling_keys = {"sample_rate_percent", "population_count", "sample_size", "created_at", "created_by_name", "items"}
    assert set(sampling_data.keys()) == expected_sampling_keys
    
    assert len(sampling_data["items"]) > 0
    item_data = sampling_data["items"][0]
    
    expected_item_keys = {"submission_id", "report_name", "checked", "checked_by_name", "changed_field_count", "visible_field_count"}
    assert set(item_data.keys()) == expected_item_keys

def test_round2_get_item_permissions(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    setup_headers(client.app.dependency_overrides, admin)
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    item = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).first()
    sid = item.submission_id
    
    # Not part of project
    outsider = User(username="out", role="user", password="")
    test_db.add(outsider)
    test_db.commit()
    setup_headers(client.app.dependency_overrides, {"id": outsider.id, "username": "out", "role": "user"})
    assert client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}").status_code == 403
    
    # Self review (Admin inputted this submission)
    setup_headers(client.app.dependency_overrides, admin)
    assert client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}").status_code == 409
    
    # Reviewer can view
    setup_headers(client.app.dependency_overrides, reviewer)
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}")
    assert res.status_code == 200
    assert res.json()["data"]["submission_id"] == sid

def test_round2_get_item_fields(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    # Setup schema with hidden column
    p1.form_schema_json_snapshot = json.dumps([{
        "fields": [
            {"name": "f1", "label": "L1", "type": "text", "col_index": 0},
            {"name": "f2", "label": "L2", "type": "text", "col_index": 1}
        ]
    }])
    p1.template_config_json_snapshot = json.dumps({"hidden_cols": [2]})
    test_db.commit()
    
    subs = make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    
    setup_headers(client.app.dependency_overrides, admin)
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    item = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).first()
    sid = item.submission_id
    
    # Set data_json for this specific submission
    sub = test_db.query(Submission).get(sid)
    sub.data_json = json.dumps({"f1": "v1", "f2": "v2"})
    
    # Also we need to update the baseline data in the item because sampling took a snapshot of it when data_json was empty
    item.baseline_data_json = sub.data_json
    test_db.commit()
    
    setup_headers(client.app.dependency_overrides, reviewer)
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}")
    assert res.status_code == 200
    fields = res.json()["data"]["fields"]
    
    assert len(fields) == 1
    assert fields[0]["name"] == "f1"
    assert fields[0]["label"] == "L1"
    assert fields[0]["value"] == "v1"
    
    # Check item and update final data with malicious hidden column update
    client.put(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}", json={"data": {"f1": "new_v1", "f2": "new_v2"}})
    
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}")
    assert res.json()["data"]["fields"][0]["value"] == "new_v1"
    
    # Verify DB directly to ensure f2 was not changed
    item_updated = test_db.query(CaseEntryQcSampleItem).filter_by(submission_id=sid).first()
    final_data = json.loads(item_updated.final_data_json)
    assert final_data.get("f2") == "v2"

def test_round2_gate_states(client, test_db, mock_data):
    admin = mock_data["admin"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    setup_headers(client.app.dependency_overrides, admin)
    make_submissions(test_db, p1.id, c1.id, mock_data["reviewer"]["id"], 5)
    
    from server.services.entry_qc_service import check_entry_qc_gate
    
    # No round2 sample
    gate = check_entry_qc_gate(test_db, p1.id, c1.id)
    assert gate["blocked"] is True
    assert gate["code"] == "entry_qc_round2_required"
    
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    # Pending round2
    gate = check_entry_qc_gate(test_db, p1.id, c1.id)
    assert gate["blocked"] is True
    assert gate["code"] == "entry_qc_round2_pending"
    
    # Disable round2 in policy
    pol = test_db.query(ProjectPolicy).first()
    pol.entry_qc_round2_enabled = False
    test_db.commit()
    gate = check_entry_qc_gate(test_db, p1.id, c1.id)
    assert gate["blocked"] is False
    
def test_round2_count_current_data(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    subs = make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    
    setup_headers(client.app.dependency_overrides, admin)
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    item = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).first()
    sid = item.submission_id
    
    sub = test_db.query(Submission).get(sid)
    sub.data_json = json.dumps({"f1": "v1"})
    item.baseline_data_json = sub.data_json
    test_db.commit()
    
    # Someone modifies the submission after sampling
    sub.data_json = json.dumps({"f1": "v1_updated"})
    test_db.commit()
    
    setup_headers(client.app.dependency_overrides, reviewer)
    # Check item without modifying what's currently in submission
    client.put(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}", json={"data": {"f1": "v1_updated"}})
    
    item = test_db.query(CaseEntryQcSampleItem).filter_by(submission_id=sid).first()
    assert item.changed_field_count == 0

def test_api_contract_round2_status_ok(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    p1.form_schema_json_snapshot = json.dumps([{"name": "f1"}])
    test_db.commit()
    
    setup_headers(client.app.dependency_overrides, admin)
    subs = make_submissions(test_db, p1.id, c1.id, reviewer["id"], 5)
    
    # GET summary
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert res.json().get("status") == "ok"
    
    # round2/sample
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    assert res.json().get("status") == "ok"
    
    sid = subs[0].id
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    items = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).all()
    
    setup_headers(client.app.dependency_overrides, admin)
    # GET item
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{items[0].submission_id}")
    assert res.json().get("status") == "ok"
    
    for item in items:
        # Simulate errors to make it fail so we can test resolve
        sub = test_db.query(Submission).get(item.submission_id)
        sub.data_json = json.dumps({"f1": "old"})
        item.baseline_data_json = sub.data_json
        test_db.commit()
        
        # PUT item
        res = client.put(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{item.submission_id}", json={"data": {"f1": "new"}})
        assert res.json().get("status") == "ok"
    
    # round2 finalize
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2")
    assert res.json().get("status") == "ok"
    
    setup_headers(client.app.dependency_overrides, admin)
    # round2/resolve
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/resolve", json={"reason": "test"})
    assert res.status_code == 200, res.text
    assert res.json().get("status") == "ok"

def test_round2_gate_failed_and_approved(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    setup_headers(client.app.dependency_overrides, admin)
    subs = make_submissions(test_db, p1.id, c1.id, reviewer["id"], 5)
    
    p1.form_schema_json_snapshot = json.dumps([{"name": "f1"}])
    pol = test_db.query(ProjectPolicy).first()
    pol.error_threshold_percent = 0 # strict threshold
    test_db.commit()
    
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    items = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).all()
    
    setup_headers(client.app.dependency_overrides, admin)
    for item in items:
        # Simulate errors
        sub = test_db.query(Submission).get(item.submission_id)
        sub.data_json = json.dumps({"f1": "old"})
        item.baseline_data_json = sub.data_json
        test_db.commit()
        
        client.put(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{item.submission_id}", json={"data": {"f1": "new"}})
        
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2")
    
    # Check gate is blocked with round2_failed
    from server.services.entry_qc_service import check_entry_qc_gate
    gate = check_entry_qc_gate(test_db, p1.id, c1.id)
    assert gate["blocked"] is True
    assert gate["code"] == "entry_qc_round2_failed"
    assert "Vòng 2 không đạt ngưỡng lỗi" in gate["message"]
    
    # Approve
    setup_headers(client.app.dependency_overrides, admin)
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/resolve", json={"reason": "ok"})
    assert res.status_code == 200, res.text
    
    # Check gate passes
    test_db.expire_all()
    gate = check_entry_qc_gate(test_db, p1.id, c1.id)
    assert gate["blocked"] is False

def test_round2_get_item_pdf(client, test_db, mock_data, tmp_path, monkeypatch):
    import os
    monkeypatch.setattr("server.routers.submissions.PDF_STORAGE_PATH", str(tmp_path))
    class MockSettings:
        pdf_storage_path = tmp_path
    monkeypatch.setattr("server.services.entry_qc_service.settings", MockSettings())
    
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    # Create fake pdf
    uuid_filename = "test.pdf"
    pdf_path = tmp_path / uuid_filename
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
    
    setup_headers(client.app.dependency_overrides, admin)
    subs = make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    sub = subs[0]
    
    # Update assignment with uuid_filename
    doc = test_db.query(AssignedDocument).get(sub.assigned_document_id)
    doc.uuid_filename = uuid_filename
    test_db.commit()
    
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    sampling = test_db.query(CaseEntryQcSampling).filter_by(case_id=c1.id).first()
    item = test_db.query(CaseEntryQcSampleItem).filter_by(sampling_id=sampling.id).first()
    
    # Update submission to be the one we know the pdf of
    item.submission_id = sub.id
    test_db.commit()
    
    sid = sub.id
    
    # Not part of project
    outsider = User(username="out", role="user", password="")
    test_db.add(outsider)
    test_db.commit()
    setup_headers(client.app.dependency_overrides, {"id": outsider.id, "username": "out", "role": "user"})
    assert client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}/pdf").status_code == 403
    
    # Self review (Admin inputted this submission)
    setup_headers(client.app.dependency_overrides, admin)
    assert client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}/pdf").status_code == 409
    
    # Reviewer can view
    setup_headers(client.app.dependency_overrides, reviewer)
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    
    # Old API works
    setup_headers(client.app.dependency_overrides, admin)
    assert client.get(f"/api/files/{uuid_filename}").status_code == 200
    
    setup_headers(client.app.dependency_overrides, {"id": outsider.id, "username": "out", "role": "user"})
    assert client.get(f"/api/files/{uuid_filename}").status_code == 403

def test_round2_get_item_report_name(client, test_db, mock_data):
    admin = mock_data["admin"]
    reviewer = mock_data["reviewer"]
    p1 = mock_data["p1"]
    c1 = mock_data["c1"]
    
    setup_headers(client.app.dependency_overrides, admin)
    subs = make_submissions(test_db, p1.id, c1.id, admin["id"], 5)
    
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/sample")
    
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    summary = res.json()["data"]
    item_in_summary = summary["round2"]["sampling"]["items"][0]
    sid = item_in_summary["submission_id"]
    expected_name = item_in_summary["report_name"]
    
    setup_headers(client.app.dependency_overrides, reviewer)
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round2/items/{sid}")
    item_in_detail = res.json()["data"]
    
    assert item_in_detail["report_name"] == expected_name


def test_round2_missing_dropdown_sent_as_empty_string(client, mock_data, test_db):
    setup_headers(client.app.dependency_overrides, mock_data['admin'])
    from server.models import Submission
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    sub = test_db.get(Submission, sub_id)
    sub.data_json = json.dumps({"field": "val1"})
    test_db.commit()

    from server.models import Project
    proj = test_db.get(Project, mock_data['p1'].id)
    proj.form_schema_json_snapshot = json.dumps([{"category": "A", "fields": [
        {"col_index": 0, "name": "field", "label": "F", "type": "text"},
        {"col_index": 1, "name": "dd", "label": "D", "type": "dropdown", "options": ["A","B"]}
    ]}])
    test_db.commit()
    
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {'field': 'val1', 'dd': ''}}
    )
    assert res.status_code == 200
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    item = r['data']['round2']['sampling']['items'][0]
    assert item['changed_field_count'] == 0
    assert item['visible_field_count'] == 2
    
    sub = test_db.get(Submission, sub_id)
    assert sub.data_json == json.dumps({"field": "val1"})

def test_round2_partial_update(client, mock_data, test_db):
    setup_headers(client.app.dependency_overrides, mock_data['admin'])
    from server.models import Submission
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    sub = test_db.get(Submission, sub_id)
    sub.data_json = json.dumps({"field": "val1", "field2": "val2"})
    test_db.commit()

    from server.models import Project
    proj = test_db.get(Project, mock_data['p1'].id)
    proj.form_schema_json_snapshot = json.dumps([{"category": "A", "fields": [
        {"col_index": 0, "name": "field", "label": "F", "type": "text"},
        {"col_index": 1, "name": "field2", "label": "D", "type": "text"}
    ]}])
    test_db.commit()
    
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {'field': 'val1', 'field2': 'val3'}}
    )
    assert res.status_code == 200
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    item = r['data']['round2']['sampling']['items'][0]
    assert item['changed_field_count'] == 1
    assert item['visible_field_count'] == 2
    
    sub = test_db.get(Submission, sub_id)
    data = json.loads(sub.data_json)
    assert data == {"field": "val1", "field2": "val3"}


def test_round2_ignores_unknown_field(client, mock_data, test_db):
    setup_headers(client.app.dependency_overrides, mock_data['admin'])
    from server.models import Submission, Project
    make_submissions(test_db, mock_data['p1'].id, mock_data['c1'].id, 999, 1)
    
    client.post(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/sample')
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    sub_id = r['data']['round2']['sampling']['items'][0]['submission_id']
    
    sub = test_db.get(Submission, sub_id)
    sub.data_json = json.dumps({"field": "val"})
    test_db.commit()

    proj = test_db.get(Project, mock_data['p1'].id)
    proj.form_schema_json_snapshot = json.dumps([{"category": "A", "fields": [
        {"col_index": 0, "name": "field", "label": "F", "type": "text"}
    ]}])
    test_db.commit()
    
    res = client.put(
        f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc/round2/items/{sub_id}',
        json={'data': {'field': 'val', 'la': 'XXX'}}
    )
    assert res.status_code == 200
    
    r = client.get(f'/api/projects/{mock_data["p1"].id}/workflow/cases/{mock_data["c1"].id}/entry-qc').json()
    item = r['data']['round2']['sampling']['items'][0]
    assert item['changed_field_count'] == 0
    assert item['visible_field_count'] == 1
    
    sub = test_db.get(Submission, sub_id)
    data = json.loads(sub.data_json)
    assert "la" not in data
    assert data == {"field": "val"}

