from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Template, User
from server.repositories.lookup_repository import LookupRepository


def _database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'lookup-cache.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _select_counter(engine, table_name):
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and f"from {table_name}" in normalized:
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", record_statement)
    return statements, record_statement


def test_user_lookups_cache_overlapping_ids_for_the_session(tmp_path):
    engine, db = _database(tmp_path)
    try:
        first = User(username="lookup-first", password="hash", role="user")
        second = User(username="lookup-second", password="hash", role="user")
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id
        statements, listener = _select_counter(engine, "users")

        first_repository = LookupRepository(db)
        second_repository = LookupRepository(db)
        assert first_repository.username_map({first_id}) == {
            first_id: "lookup-first"
        }
        assert second_repository.existing_user_ids({first_id, second_id}) == {
            first_id,
            second_id,
        }
        assert second_repository.user_exists(second_id) is True
        assert first_repository.username_map({first_id, second_id}) == {
            first_id: "lookup-first",
            second_id: "lookup-second",
        }

        assert len(statements) == 2
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        db.close()
        engine.dispose()


def test_template_entity_and_name_share_one_cached_query(tmp_path):
    engine, db = _database(tmp_path)
    try:
        template = Template(name="Lookup template", filename="lookup.xlsx")
        db.add(template)
        db.commit()
        template_id = template.id
        statements, listener = _select_counter(engine, "templates")
        repository = LookupRepository(db)

        assert repository.template_name_map({template_id}) == {
            template_id: "Lookup template"
        }
        assert repository.get_template(template_id).id == template_id
        assert len(statements) == 1
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        db.close()
        engine.dispose()


def test_lookup_cache_is_invalidated_after_commit(tmp_path):
    engine, db = _database(tmp_path)
    try:
        user = User(username="before-update", password="hash", role="user")
        db.add(user)
        db.commit()
        user_id = user.id
        statements, listener = _select_counter(engine, "users")
        repository = LookupRepository(db)

        assert repository.username_map({user_id})[user_id] == "before-update"
        user.username = "after-update"
        db.commit()
        assert repository.username_map({user_id})[user_id] == "after-update"
        assert len(statements) == 2
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        db.close()
        engine.dispose()


def test_negative_lookup_cache_is_cleared_when_entity_is_created(tmp_path):
    engine, db = _database(tmp_path)
    try:
        repository = LookupRepository(db)
        statements, listener = _select_counter(engine, "users")

        assert repository.user_exists(9001) is False
        assert repository.user_exists(9001) is False
        db.add(User(id=9001, username="created-later", password="hash", role="user"))
        db.commit()
        assert repository.user_exists(9001) is True

        assert len(statements) == 2
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        db.close()
        engine.dispose()


def test_lookup_cache_is_invalidated_after_rollback(tmp_path):
    engine, db = _database(tmp_path)
    try:
        user = User(username="persisted-name", password="hash", role="user")
        db.add(user)
        db.commit()
        user_id = user.id
        statements, listener = _select_counter(engine, "users")
        repository = LookupRepository(db)

        assert repository.username_map({user_id})[user_id] == "persisted-name"
        user.username = "rolled-back-name"
        db.rollback()
        assert repository.username_map({user_id})[user_id] == "persisted-name"
        assert len(statements) == 2
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        db.close()
        engine.dispose()
