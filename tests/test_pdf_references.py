import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.routers import submissions
from server.services.submission_service import SubmissionService, _pdf_url
from server.utils.folder_utils import folder_path_key
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


def test_submission_list_reads_pre_migrated_pdf_metadata_without_writing():
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
                assigned_document_id=7,
                folder_path='tlm/HOANHMO/001/0002',
                folder_path_key=folder_path_key('tlm/HOANHMO/001/0002'),
                data_json=json.dumps({
                    '_pdf_filename': '001.pdf',
                    '_pdf_uuid': 'uuid_001.pdf',
                }),
            ),
        ])
        test_session.commit()
        before = test_session.get(Submission, 11)
        metadata_before = (
            before.assigned_document_id,
            before.folder_path,
            before.folder_path_key,
        )

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
        test_session.expire_all()
        after = test_session.get(Submission, 11)
        assert (
            after.assigned_document_id,
            after.folder_path,
            after.folder_path_key,
        ) == metadata_before
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
                assigned_document_id=21,
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
                assigned_document_id=41,
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


def test_reviewer_opening_pending_submission_recovers_document_review_assignment():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine)()
    try:
        test_session.add_all([
            User(id=2, username='input', password='hash', role='user'),
            User(id=3, username='reviewer', password='hash', role='user'),
            AssignedDocument(
                id=20,
                original_filename='form.pdf',
                uuid_filename='review-form.pdf',
                assigned_to_user_id=2,
                status='completed',
            ),
            AssignedDocumentReviewAssignment(document_id=20, reviewer_user_id=3),
            Submission(
                id=30,
                assigned_document_id=20,
                created_by_user_id=2,
                status='pending_review',
                data_json=json.dumps({
                    '_pdf_filename': 'form.pdf',
                    '_pdf_uuid': 'review-form.pdf',
                }),
            ),
        ])
        test_session.commit()

        result = submissions.api_get_submission(
            30,
            current_user={'id': 3, 'role': 'user'},
            db=test_session,
        )

        assignment = test_session.query(SubmissionReviewAssignment).filter_by(
            submission_id=30,
        ).one()
        assert result['status'] == 'ok'
        assert result['can_review'] is True
        assert assignment.reviewer_user_id == 3
    finally:
        test_session.close()


def test_file_download_rejects_another_user():
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


def test_file_download_does_not_fallback_to_legacy_submission(monkeypatch):
    legacy_submission = SimpleNamespace(data_json=json.dumps({
        '_pdf_filename': 'legacy.pdf',
        '_pdf_uuid': 'legacy-uuid.pdf',
    }))
    db = FakeDb(rows={Submission: legacy_submission})
    monkeypatch.setattr(submissions.os.path, 'isfile', lambda _path: True)

    with pytest.raises(HTTPException, match='File không tồn tại') as error:
        submissions.api_get_pdf_file(
            'legacy-uuid.pdf',
            current_user={'id': 1, 'role': 'admin'},
            db=db,
        )

    assert error.value.status_code == 404
