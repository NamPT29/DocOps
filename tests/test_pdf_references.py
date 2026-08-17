import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from server.database import Base
from server.routers import submissions
from server.services.submission_service import SubmissionService, _pdf_url
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)


class FakeQuery:
    def __init__(self, document):
        self.document = document

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return self.document


class FakeDb:
    def __init__(self, document=None, rows=None):
        self.document = document
        self.rows = rows or {}
        self.added = None
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        value = self.rows.get(model)
        if value is None and model is AssignedDocument:
            value = self.document
        return FakeQuery(value)

    def add(self, value):
        self.added = value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_enriches_legacy_pdf_name_with_stored_uuid():
    document = SimpleNamespace(
        id=1,
        original_filename='CT 909101-GCN.pdf',
        uuid_filename='abc_CT 909101-GCN.pdf',
    )

    data, resolved = SubmissionService.enrich_pdf_reference(
        {'_pdf_filename': 'CT 909101-GCN.pdf'}, FakeDb(document), owner_id=2
    )

    assert resolved is document
    assert data['_pdf_uuid'] == 'abc_CT 909101-GCN.pdf'
    assert data['_pdf_url'] == '/api/files/abc_CT%20909101-GCN.pdf'


def test_enriches_report_with_authoritative_pdf_and_folder_paths():
    document = SimpleNamespace(
        id=7,
        original_filename='001.pdf',
        uuid_filename='uuid_001.pdf',
    )
    path = SimpleNamespace(relative_path='tlm/HOANHMO/001/0001/001.pdf')
    folder = SimpleNamespace(folder_group='tlm/HOANHMO/001/0001')
    db = FakeDb(document, {
        AssignedDocument: document,
        AssignedDocumentPath: path,
        AssignedDocumentFolder: folder,
    })

    data, resolved = SubmissionService.enrich_pdf_reference(
        {
            '_pdf_uuid': 'uuid_001.pdf',
            '_pdf_relative_path': 'đường/dẫn/giả.pdf',
            '_folder_path': 'folder/giả',
        },
        db,
        owner_id=2,
    )

    assert resolved is document
    assert data['_pdf_relative_path'] == 'tlm/HOANHMO/001/0001/001.pdf'
    assert data['_folder_path'] == 'tlm/HOANHMO/001/0001'


def test_submission_list_backfills_linked_pdf_path_for_legacy_draft():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine)()
    try:
        test_session.add_all([
            User(id=2, username='nhanvien', password='hash', role='user'),
            User(id=4, username='kiemduyet', password='hash', role='user'),
            Template(id=3, name='Nhóm tài liệu', filename='nhom.xlsx'),
            AssignedDocument(
                id=7,
                original_filename='001.pdf',
                uuid_filename='uuid_001.pdf',
                assigned_to_user_id=2,
                template_id=3,
                status='pending',
            ),
            AssignedDocumentPath(
                document_id=7,
                relative_path='tlm/HOANHMO/001/0002/001.pdf',
                upload_id='legacy-upload',
            ),
            AssignedDocumentFolder(
                document_id=7,
                folder_group='tlm/HOANHMO/001/0002',
            ),
            AssignedDocumentReviewAssignment(
                document_id=7,
                reviewer_user_id=4,
            ),
            Submission(
                id=11,
                template_id=3,
                created_by_user_id=2,
                status='draft',
                data_json=json.dumps({
                    '_pdf_filename': '001.pdf',
                    '_pdf_uuid': 'uuid_001.pdf',
                }),
            ),
        ])
        test_session.commit()

        result = submissions.api_get_submissions(
            current_user={'id': 2, 'role': 'user'},
            db=test_session,
        )

        assert result['status'] == 'ok'
        assert result['data'][0]['template'] == 'Nhóm tài liệu'
        assert result['data'][0]['creator_name'] == 'nhanvien'
        assert result['data'][0]['reviewer_name'] == 'kiemduyet'
        assert result['data'][0]['pdf_relative_path'] == 'tlm/HOANHMO/001/0002/001.pdf'
        assert result['data'][0]['folder_path'] == 'tlm/HOANHMO/001/0002'
    finally:
        test_session.close()


def test_reviewer_gets_every_pdf_from_the_submission_folder():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine)()
    try:
        test_session.add_all([
            User(id=2, username='input', password='hash', role='user'),
            User(id=3, username='reviewer', password='hash', role='user'),
            Template(id=4, name='Nhóm hồ sơ', filename='nhom.xlsx'),
            AssignedDocument(
                id=20, original_filename='bia.pdf', uuid_filename='uuid-bia.pdf',
                assigned_to_user_id=2, template_id=4, status='completed',
            ),
            AssignedDocument(
                id=21, original_filename='form-1.pdf', uuid_filename='uuid-form-1.pdf',
                assigned_to_user_id=2, template_id=4, status='completed',
            ),
            AssignedDocumentFolder(document_id=20, folder_group='001/0001'),
            AssignedDocumentFolder(document_id=21, folder_group='001/0001'),
            AssignedDocumentPath(
                document_id=20, relative_path='001/0001/bia.pdf', upload_id='cover',
            ),
            AssignedDocumentPath(
                document_id=21, relative_path='001/0001/form-1.pdf', upload_id='form',
            ),
            AssignedDocumentReviewAssignment(document_id=20, reviewer_user_id=3),
            AssignedDocumentReviewAssignment(document_id=21, reviewer_user_id=3),
            Submission(
                id=30, template_id=4, created_by_user_id=2, status='pending_review',
                data_json=json.dumps({
                    '_pdf_filename': 'form-1.pdf',
                    '_pdf_uuid': 'uuid-form-1.pdf',
                }),
            ),
            SubmissionReviewAssignment(submission_id=30, reviewer_user_id=3),
        ])
        test_session.commit()

        result = submissions.api_get_submission(
            30,
            current_user={'id': 3, 'role': 'user'},
            db=test_session,
        )

        assert result['status'] == 'ok'
        assert result['can_review'] is True
        assert [item['name'] for item in result['folder_files']] == [
            'bia.pdf',
            'form-1.pdf',
        ]
        assert {item['folder_group'] for item in result['folder_files']} == {'001/0001'}
    finally:
        test_session.close()


def test_admin_opening_review_also_gets_every_pdf_from_the_folder():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine)()
    try:
        test_session.add_all([
            User(id=1, username='admin', password='hash', role='admin'),
            User(id=2, username='input', password='hash', role='user'),
            AssignedDocument(
                id=40, original_filename='bia.pdf', uuid_filename='admin-bia.pdf',
                assigned_to_user_id=2, status='completed',
            ),
            AssignedDocument(
                id=41, original_filename='form.pdf', uuid_filename='admin-form.pdf',
                assigned_to_user_id=2, status='completed',
            ),
            AssignedDocumentFolder(document_id=40, folder_group='002/0003'),
            AssignedDocumentFolder(document_id=41, folder_group='002/0003'),
            AssignedDocumentPath(
                document_id=40, relative_path='002/0003/bia.pdf', upload_id='admin-cover',
            ),
            AssignedDocumentPath(
                document_id=41, relative_path='002/0003/form.pdf', upload_id='admin-form',
            ),
            Submission(
                id=42, created_by_user_id=2, status='pending_review',
                data_json=json.dumps({
                    '_pdf_filename': 'form.pdf',
                    '_pdf_uuid': 'admin-form.pdf',
                }),
            ),
        ])
        test_session.commit()

        result = submissions.api_get_submission(
            42,
            current_user={'id': 1, 'role': 'admin'},
            db=test_session,
        )

        assert result['status'] == 'ok'
        assert result['can_review'] is True
        assert [item['name'] for item in result['folder_files']] == ['bia.pdf', 'form.pdf']
    finally:
        test_session.close()


def test_builds_url_for_manual_upload_uuid_without_assignment():
    data, resolved = SubmissionService.enrich_pdf_reference(
        {
            '_pdf_filename': 'Hồ sơ.pdf',
            '_pdf_uuid': 'uuid_Hồ sơ.pdf',
        },
        FakeDb(),
        owner_id=2,
        allow_unregistered=True,
    )

    assert resolved is None
    assert data['_pdf_url'] == _pdf_url('uuid_Hồ sơ.pdf')
    assert data['_pdf_url'] == '/api/files/uuid_H%E1%BB%93%20s%C6%A1.pdf'


def test_manual_upload_uses_configured_pdf_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(submissions, 'PDF_STORAGE_PATH', str(tmp_path))
    upload = UploadFile(filename='Hồ sơ.pdf', file=BytesIO(b'%PDF-test'))
    db = FakeDb()

    result = asyncio.run(
        submissions.api_upload_pdf(upload, current_user={'id': 2}, db=db)
    )

    assert result['status'] == 'ok'
    assert result['name'] == 'Hồ sơ.pdf'
    assert result['uuid'].endswith('_Hồ sơ.pdf')
    assert result['url'].startswith('/api/files/')
    assert (tmp_path / result['uuid']).read_bytes() == b'%PDF-test'
    assert db.added.uuid_filename == result['uuid']
    assert db.added.assigned_to_user_id == 2
    assert db.committed


def test_manual_upload_rejects_disguised_html(monkeypatch, tmp_path):
    monkeypatch.setattr(submissions, 'PDF_STORAGE_PATH', str(tmp_path))
    upload = UploadFile(filename='attack.pdf', file=BytesIO(b'<script>alert(1)</script>'))
    db = FakeDb()

    with pytest.raises(HTTPException, match='Nội dung file không đúng định dạng') as error:
        asyncio.run(submissions.api_upload_pdf(upload, current_user={'id': 2}, db=db))

    assert error.value.status_code == 400
    assert db.rolled_back
    assert list(tmp_path.iterdir()) == []


def test_file_download_rejects_another_user(tmp_path, monkeypatch):
    monkeypatch.setattr(submissions, 'PDF_STORAGE_PATH', str(tmp_path))
    document = SimpleNamespace(
        id=1,
        original_filename='private.pdf',
        uuid_filename='uuid_private.pdf',
        assigned_to_user_id=3,
    )

    with pytest.raises(HTTPException, match='Không có quyền truy cập') as error:
        submissions.api_get_pdf_file(
            'uuid_private.pdf',
            current_user={'id': 2, 'role': 'user'},
            db=FakeDb(document),
        )

    assert error.value.status_code == 403
