import pytest
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.database import Base, get_utc_now
from server.models import (
    AssignedDocument,
    AssignedDocumentReviewAssignment,
    User,
    UserLoginSession,
)
from server.routers import auth


@pytest.mark.parametrize("user_count", [1, 50])
def test_get_users_query_count_is_bounded_and_payload_is_unchanged(user_count):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as setup_db:
        users = [
            User(
                username="admin" if index == 0 else f"user-{index}",
                password="not-used",
                full_name="Administrator" if index == 0 else f"User {index}",
                phone_number=None if index == 0 else f"0900{index:06d}",
                role="admin" if index == 0 else "user",
            )
            for index in range(user_count)
        ]
        setup_db.add_all(users)
        setup_db.flush()

        if user_count >= 3:
            document = AssignedDocument(
                original_filename="assigned.pdf",
                uuid_filename="assigned-query-count.pdf",
                assigned_to_user_id=users[1].id,
            )
            setup_db.add(document)
            setup_db.flush()
            setup_db.add(
                AssignedDocumentReviewAssignment(
                    document_id=document.id,
                    reviewer_user_id=users[2].id,
                )
            )
        admin_id = users[0].id
        login_session = UserLoginSession(
            session_id=f"query-count-session-{user_count}",
            user_id=admin_id,
            browser_id=f"query-count-browser-{user_count}",
            expires_at=get_utc_now() + timedelta(minutes=10),
        )
        setup_db.add(login_session)
        setup_db.commit()
        login_session_id = login_session.session_id

    app = FastAPI()
    app.include_router(auth.router)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[auth.get_db] = override_get_db
    token = auth.jwt.encode(
        {"sub": str(admin_id), "sid": login_session_id},
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    select_statements = []

    def record_select(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_select)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/users",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        event.remove(engine, "before_cursor_execute", record_select)
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert len(payload["data"]) == user_count
    assert len(select_statements) == 4

    users_by_name = {user["username"]: user for user in payload["data"]}
    assert users_by_name["admin"] == {
        "id": admin_id,
        "username": "admin",
        "full_name": "Administrator",
        "phone_number": None,
        "role": "admin",
        "max_concurrent_sessions": 1,
        "active_session_count": 1,
        "can_input": True,
        "can_review": True,
        "roles": ["admin", "input", "reviewer"],
    }
    if user_count >= 3:
        assert users_by_name["user-1"]["can_input"] is True
        assert users_by_name["user-1"]["can_review"] is False
        assert users_by_name["user-1"]["roles"] == ["input"]
        assert users_by_name["user-2"]["can_input"] is False
        assert users_by_name["user-2"]["can_review"] is True
        assert users_by_name["user-2"]["roles"] == ["reviewer"]
        assert users_by_name["user-3"]["can_input"] is False
        assert users_by_name["user-3"]["can_review"] is False
        assert users_by_name["user-3"]["roles"] == []
