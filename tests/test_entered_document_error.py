"""Lưu hồ sơ mới cho file đã có hồ sơ nhập: báo rõ, không dùng câu "không thuộc người dùng"."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import AssignedDocument, Submission, User
from server.routers import submissions
from server.services.submission_service import ENTERED_DOCUMENT_MESSAGE, SubmissionService


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'entered.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db):
    owner = User(username="a", password="x", role="user")
    other = User(username="c", password="x", role="user")
    db.add_all([owner, other])
    db.flush()
    documents = {
        "pending": AssignedDocument(original_filename="1.pdf", uuid_filename="pending.pdf", assigned_to_user_id=owner.id, status="pending"),
        "done": AssignedDocument(original_filename="2.pdf", uuid_filename="done.pdf", assigned_to_user_id=owner.id, status="completed"),
        "replaced": AssignedDocument(original_filename="3.pdf", uuid_filename="replaced.pdf", assigned_to_user_id=owner.id, status="replaced"),
        "foreign": AssignedDocument(original_filename="4.pdf", uuid_filename="foreign.pdf", assigned_to_user_id=other.id, status="completed"),
    }
    db.add_all(documents.values())
    db.commit()
    return owner, documents


def enrich(db, owner, uuid):
    return SubmissionService.enrich_pdf_reference({"_pdf_uuid": uuid}, db, owner.id, pending_only=True)


def test_pending_document_of_the_user_is_accepted(db, world):
    owner, documents = world

    _data, document = enrich(db, owner, "pending.pdf")

    assert document.id == documents["pending"].id


def test_document_that_already_has_a_record_gets_a_clear_conflict_message(db, world):
    owner, _documents = world

    with pytest.raises(HTTPException) as error:
        enrich(db, owner, "done.pdf")

    assert error.value.status_code == 409
    assert error.value.detail == ENTERED_DOCUMENT_MESSAGE
    assert "Hồ sơ đã nhập" in error.value.detail
    assert "không thuộc" not in error.value.detail


def test_another_users_document_keeps_the_ownership_message(db, world):
    owner, _documents = world

    with pytest.raises(HTTPException) as error:
        enrich(db, owner, "foreign.pdf")

    assert error.value.status_code == 400
    assert error.value.detail == "File đính kèm không thuộc người dùng"


@pytest.mark.parametrize("uuid", ["replaced.pdf", "khong-co.pdf"])
def test_inactive_or_unknown_file_does_not_claim_it_was_entered(db, world, uuid):
    owner, _documents = world

    with pytest.raises(HTTPException) as error:
        enrich(db, owner, uuid)

    assert error.value.status_code == 400
    assert error.value.detail == "File đính kèm không thuộc người dùng"


def test_saving_a_new_draft_for_an_entered_file_is_refused_without_writing(db, world):
    owner, _documents = world

    with pytest.raises(HTTPException) as error:
        submissions.api_submit(
            submissions.SubmitRequest(data={"_pdf_uuid": "done.pdf", "col_0": "x"}, status="draft"),
            current_user={"id": owner.id},
            db=db,
        )

    assert error.value.status_code == 409
    assert db.query(Submission).count() == 0
