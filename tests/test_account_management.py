import inspect as python_inspect

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import User
from server.routers import auth
from server.services.user_profile_service import ensure_user_profile_schema


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_legacy_user_schema_migration_adds_fields_and_backfills_name():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(255) NOT NULL, "
            "password VARCHAR(255) NOT NULL, role VARCHAR(255))"
        ))
        connection.execute(text(
            "INSERT INTO users (id, username, password, role) "
            "VALUES (1, 'legacy-user', 'legacy-password', 'user')"
        ))

    ensure_user_profile_schema(engine)
    ensure_user_profile_schema(engine)

    assert {column["name"] for column in inspect(engine).get_columns("users")} >= {
        "full_name",
        "phone_number",
        "max_concurrent_sessions",
    }
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT full_name, phone_number FROM users WHERE id = 1"
        )).one()
    assert row.full_name == "legacy-user"
    assert row.phone_number is None
    with engine.connect() as connection:
        session_limit = connection.execute(text(
            "SELECT max_concurrent_sessions FROM users WHERE id = 1"
        )).scalar_one()
    assert session_limit == 1
    engine.dispose()


def test_create_edit_and_change_password_preserve_profile_and_hashing():
    engine, db = _database()
    try:
        admin = User(
            username="admin",
            password=auth.hash_password("admin-password"),
            full_name="Administrator",
            role="admin",
        )
        db.add(admin)
        db.commit()
        current_admin = {"id": admin.id, "username": admin.username, "role": "admin"}

        created = auth.api_create_user(
            auth.CreateUserRequest(
                username="employee",
                password="employee-password",
                full_name="  ",
                phone_number=" 0901 234 567 ",
            ),
            current_user=current_admin,
            db=db,
        )["user"]
        user = db.get(User, created["id"])
        assert created["full_name"] == "employee"
        assert created["phone_number"] == "0901 234 567"
        assert created["max_concurrent_sessions"] == 1
        assert auth.verify_password("employee-password", user.password)
        original_hash = user.password

        updated = auth.api_update_user_profile(
            user.id,
            auth.UpdateUserProfileRequest(
                full_name=" Nguyễn Văn A ",
                phone_number=" 0988 000 111 ",
            ),
            current_user=current_admin,
            db=db,
        )["user"]
        assert updated["full_name"] == "Nguyễn Văn A"
        assert updated["phone_number"] == "0988 000 111"
        assert user.password == original_hash

        auth.api_change_user_password(
            user.id,
            auth.ChangePasswordRequest(new_password="replacement-password"),
            current_user=current_admin,
            db=db,
        )
        assert user.password != original_hash
        assert auth.verify_password("replacement-password", user.password)
        assert not auth.verify_password("employee-password", user.password)
    finally:
        db.close()
        engine.dispose()


def test_account_mutations_keep_admin_authorization_dependency():
    for endpoint in (
        auth.api_create_user,
        auth.api_update_user_profile,
        auth.api_change_user_password,
        auth.api_revoke_user_sessions,
    ):
        dependency = python_inspect.signature(endpoint).parameters["current_user"].default
        assert dependency.dependency is auth.get_admin_user
