import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from server.routers import submissions
from server.routers.submissions import _enrich_pdf_reference, _pdf_url


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
    def __init__(self, document=None):
        self.document = document
        self.added = None
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return FakeQuery(self.document)

    def add(self, value):
        self.added = value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_enriches_legacy_pdf_name_with_stored_uuid():
    document = SimpleNamespace(
        original_filename='CT 909101-GCN.pdf',
        uuid_filename='abc_CT 909101-GCN.pdf',
    )

    data, resolved = _enrich_pdf_reference(
        {'_pdf_filename': 'CT 909101-GCN.pdf'}, FakeDb(document), owner_id=2
    )

    assert resolved is document
    assert data['_pdf_uuid'] == 'abc_CT 909101-GCN.pdf'
    assert data['_pdf_url'] == '/api/files/abc_CT%20909101-GCN.pdf'


def test_builds_url_for_manual_upload_uuid_without_assignment():
    data, resolved = _enrich_pdf_reference(
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
