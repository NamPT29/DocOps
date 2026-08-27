from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from server.routers import auth, submissions
from server.services.login_rate_limit_service import LoginRateLimiter


class StaticQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return self.value


class StaticDb:
    def __init__(self, value=None):
        self.value = value
        self.added = None
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return StaticQuery(self.value)

    def add(self, value):
        self.added = value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_password_hash_and_legacy_login_migration(monkeypatch):
    user = SimpleNamespace(id=7, username='legacy', password='old-password', role='user')
    db = StaticDb(user)
    request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))

    result = auth.api_login(
        auth.LoginRequest(username='legacy', password='old-password'),
        request=request,
        db=db,
    )

    assert result['status'] == 'ok'
    assert user.password.startswith('scrypt$')
    assert auth.verify_password('old-password', user.password)
    assert not auth.verify_password('wrong-password', user.password)
    assert db.committed


def test_signed_token_cannot_impersonate_deleted_user():
    token = jwt.encode({'sub': '999', 'role': 'admin'}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)

    with pytest.raises(HTTPException, match='User no longer exists') as error:
        auth.get_current_user(f'Bearer {token}', db=StaticDb())

    assert error.value.status_code == 401


def test_token_role_is_reloaded_from_database():
    user = SimpleNamespace(id=7, username='member', role='user')
    token = jwt.encode({'sub': '7', 'role': 'admin'}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)

    current_user = auth.get_current_user(f'Bearer {token}', db=StaticDb(user))

    assert current_user == {'id': 7, 'username': 'member', 'role': 'user'}


def test_user_cannot_submit_an_admin_only_status():
    with pytest.raises(ValidationError):
        submissions.SubmitRequest(data={}, status='completed')


def test_submission_defaults_to_draft():
    db = StaticDb()

    result = submissions.api_submit(
        submissions.SubmitRequest(data={}),
        current_user={'id': 2},
        db=db,
    )

    assert result == {'status': 'ok'}
    assert db.added.status == 'draft'
    assert db.committed


def test_saving_draft_marks_only_an_owned_document_as_entered():
    document = SimpleNamespace(
        id=9,
        original_filename='case.pdf',
        uuid_filename='uuid_case.pdf',
        assigned_to_user_id=2,
        status='pending',
    )
    db = StaticDb(document)

    result = submissions.api_submit(
        submissions.SubmitRequest(
            data={'_pdf_uuid': document.uuid_filename},
            status='draft',
        ),
        current_user={'id': 2},
        db=db,
    )

    assert result == {'status': 'ok'}
    assert db.added.status == 'draft'
    assert document.status == 'completed'


def test_unowned_attachment_returns_http_error_instead_of_success_payload():
    db = StaticDb()

    with pytest.raises(HTTPException, match='File đính kèm không thuộc người dùng') as error:
        submissions.api_submit(
            submissions.SubmitRequest(data={'_pdf_uuid': 'not-owned.pdf'}),
            current_user={'id': 2},
            db=db,
        )

    assert error.value.status_code == 400
    assert db.rolled_back
