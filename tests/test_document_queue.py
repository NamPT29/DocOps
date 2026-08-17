"""Tests for DocumentRepository.list_input_queue and linked_pdf_uuids.

These functions filter out documents that already have submissions (either via
assigned_document_id or via legacy JSON matching).  The optimisation replaces
a giant‑string substring scan with parsed‑JSON set lookups.
"""

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    Submission,
    Template,
    User,
)
from server.repositories.document_repository import DocumentRepository


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # -- seed a template
    tpl = Template(name="TestTemplate", filename="t.xlsx")
    session.add(tpl)
    session.flush()

    # -- seed a user
    user = User(username="worker", password="x", role="input")
    session.add(user)
    session.flush()

    yield session, user.id, tpl.id
    session.close()


# ── helpers ──────────────────────────────────────────────────────────────────
def _add_document(session, user_id, tpl_id, uuid, original, folder=None):
    doc = AssignedDocument(
        assigned_to_user_id=user_id,
        template_id=tpl_id,
        uuid_filename=uuid,
        original_filename=original,
        status="pending",
    )
    session.add(doc)
    session.flush()
    if folder:
        session.add(AssignedDocumentFolder(document_id=doc.id, folder_group=folder))
        session.flush()
    return doc


def _add_submission(session, user_id, tpl_id, doc=None, pdf_uuid=None, pdf_filename=None):
    data = {}
    if pdf_uuid:
        data["_pdf_uuid"] = pdf_uuid
    if pdf_filename:
        data["_pdf_filename"] = pdf_filename
    sub = Submission(
        data_json=json.dumps(data, ensure_ascii=False),
        template_id=tpl_id,
        created_by_user_id=user_id,
        assigned_document_id=doc.id if doc else None,
    )
    session.add(sub)
    session.flush()
    return sub


# ── list_input_queue tests ───────────────────────────────────────────────────
class TestListInputQueue:

    def test_returns_pending_docs(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_document(session, uid, tid, "bbb.pdf", "file_b.pdf")
        session.commit()

        result = DocumentRepository(session).list_input_queue(uid)
        assert len(result) == 2

    def test_excludes_docs_with_assigned_submission(self, db):
        session, uid, tid = db
        doc_a = _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_document(session, uid, tid, "bbb.pdf", "file_b.pdf")
        _add_submission(session, uid, tid, doc=doc_a)
        session.commit()

        result = DocumentRepository(session).list_input_queue(uid)
        assert len(result) == 1
        assert result[0][0].uuid_filename == "bbb.pdf"

    def test_excludes_docs_matched_by_legacy_uuid(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_document(session, uid, tid, "bbb.pdf", "file_b.pdf")
        # Legacy submission references aaa.pdf by uuid but has no assigned_document_id
        _add_submission(session, uid, tid, pdf_uuid="aaa.pdf")
        session.commit()

        result = DocumentRepository(session).list_input_queue(uid)
        assert len(result) == 1
        assert result[0][0].uuid_filename == "bbb.pdf"

    def test_excludes_docs_matched_by_legacy_filename(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_document(session, uid, tid, "bbb.pdf", "file_b.pdf")
        # Legacy submission references file_a.pdf by original_filename
        _add_submission(session, uid, tid, pdf_filename="file_a.pdf")
        session.commit()

        result = DocumentRepository(session).list_input_queue(uid)
        assert len(result) == 1
        assert result[0][0].uuid_filename == "bbb.pdf"

    def test_empty_when_all_submitted(self, db):
        session, uid, tid = db
        doc = _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_submission(session, uid, tid, doc=doc)
        session.commit()

        result = DocumentRepository(session).list_input_queue(uid)
        assert result == []

    def test_empty_when_no_docs(self, db):
        session, uid, tid = db
        result = DocumentRepository(session).list_input_queue(uid)
        assert result == []


# ── linked_pdf_uuids tests ──────────────────────────────────────────────────
class TestLinkedPdfUuids:

    def test_includes_docs_with_assigned_submission(self, db):
        session, uid, tid = db
        doc = _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_submission(session, uid, tid, doc=doc)
        session.commit()

        result = DocumentRepository(session).linked_pdf_uuids(uid)
        assert "aaa.pdf" in result

    def test_includes_docs_matched_by_legacy_uuid(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_submission(session, uid, tid, pdf_uuid="aaa.pdf")
        session.commit()

        result = DocumentRepository(session).linked_pdf_uuids(uid)
        assert "aaa.pdf" in result

    def test_includes_docs_matched_by_legacy_filename(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        _add_submission(session, uid, tid, pdf_filename="file_a.pdf")
        session.commit()

        result = DocumentRepository(session).linked_pdf_uuids(uid)
        assert "aaa.pdf" in result

    def test_excludes_unlinked_docs(self, db):
        session, uid, tid = db
        _add_document(session, uid, tid, "aaa.pdf", "file_a.pdf")
        session.commit()

        result = DocumentRepository(session).linked_pdf_uuids(uid)
        assert "aaa.pdf" not in result

    def test_empty_when_no_docs(self, db):
        session, uid, tid = db
        result = DocumentRepository(session).linked_pdf_uuids(uid)
        assert result == set()
