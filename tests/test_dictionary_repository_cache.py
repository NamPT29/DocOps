from cachetools import TTLCache
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Dictionary, DictionaryItem, Template
from server.repositories import dictionary_repository
from server.repositories.dictionary_repository import DictionaryRepository


def _seed_dictionary(db):
    template = Template(name="Cache form", filename="cache.xlsx")
    db.add(template)
    db.flush()
    dictionary = Dictionary(template_id=template.id, name="Dân tộc")
    db.add(dictionary)
    db.flush()
    db.add(DictionaryItem(dictionary_id=dictionary.id, code="01", value="Kinh"))
    db.commit()
    return template, dictionary


def test_option_map_reuses_query_and_does_not_expose_cached_lists(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'dictionary-cache.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        template, _dictionary = _seed_dictionary(db)
        dictionary_repository._OPTION_MAP_CACHE.clear()
        select_count = 0

        def count_dictionary_selects(_connection, _cursor, statement, *_args):
            nonlocal select_count
            if "FROM dictionaries" in statement:
                select_count += 1

        event.listen(engine, "before_cursor_execute", count_dictionary_selects)
        try:
            repository = DictionaryRepository(db)
            first = repository.option_map_for_template(template.id)
            first["Dân tộc"].append("99 - Đã sửa ngoài cache")
            second = repository.option_map_for_template(template.id)
        finally:
            event.remove(engine, "before_cursor_execute", count_dictionary_selects)

        assert second == {"Dân tộc": ["01 - Kinh"]}
        assert select_count == 1

    dictionary_repository._OPTION_MAP_CACHE.clear()
    engine.dispose()


def test_option_map_refreshes_after_cross_worker_ttl(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'dictionary-cache-ttl.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = [0.0]
    monkeypatch.setattr(
        dictionary_repository,
        "_OPTION_MAP_CACHE",
        TTLCache(maxsize=100, ttl=10, timer=lambda: now[0]),
    )

    with session_factory() as db:
        template, dictionary = _seed_dictionary(db)
        repository = DictionaryRepository(db)
        assert repository.option_map_for_template(template.id) == {
            "Dân tộc": ["01 - Kinh"]
        }

        # A Core update simulates a commit in another worker; ORM mapper events
        # in this process therefore do not invalidate the local cache.
        db.execute(
            update(DictionaryItem)
            .where(DictionaryItem.dictionary_id == dictionary.id)
            .values(value="Kinh mới")
        )
        db.commit()
        assert repository.option_map_for_template(template.id) == {
            "Dân tộc": ["01 - Kinh"]
        }

        now[0] = 11.0
        assert repository.option_map_for_template(template.id) == {
            "Dân tộc": ["01 - Kinh mới"]
        }

    engine.dispose()
