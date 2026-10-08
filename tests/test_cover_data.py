"""Bìa hồ sơ dùng chung theo thư mục (lát F1): đọc bìa đã lưu, đồng bộ bìa."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Submission, Template, User
from server.routers import submissions
from server.services.submission_service import SubmissionService, cover_scope_folder

COVER = {"cover_cols": [1, 2], "cover_folder_level": 1}


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'cover.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def user_dict(user):
    return {"id": user.id, "username": user.username, "full_name": user.username, "role": user.role, "session_id": "s"}


@pytest.fixture()
def world(db):
    owner = User(username="a", password="x", role="user")
    other = User(username="c", password="x", role="user")
    admin = User(username="admin", password="x", role="admin")
    template = Template(name="HS", filename="hs.xlsx", config_json=json.dumps(COVER))
    db.add_all([owner, other, admin, template])
    db.commit()
    return owner, other, admin, template


def add(db, template, user, folder, **cols):
    sub = Submission(
        template_id=template.id,
        created_by_user_id=user.id,
        folder_path=folder,
        data_json=json.dumps(cols, ensure_ascii=False),
    )
    db.add(sub)
    db.commit()
    return sub


def cover(db, template, user, folder):
    return submissions.api_get_cover_data(
        template_id=template.id, folder_path=folder, current_user=user_dict(user), db=db
    )


@pytest.mark.parametrize(
    "folder, level, scope",
    [("A/B/C/D", 1, "A/B/C/D"), ("A/B/C/D", 2, "A/B/C"), ("A/B/C/D", 0, "A/B/C/D"), ("A/B", 5, "A/B")],
)
def test_cover_scope_folder_matches_the_sync_rule(folder, level, scope):
    assert cover_scope_folder(folder, level) == scope


def test_returns_only_cover_columns_of_the_latest_record_in_the_folder(db, world):
    owner, _other, _admin, template = world
    add(db, template, owner, "p/2/cv", col_0="Bìa cũ", col_1="01/01/2006", col_4="văn bản 1")
    add(db, template, owner, "p/2/cv", col_0="Bìa mới", col_1="31/08/2006", col_4="văn bản 2")

    result = cover(db, template, owner, "p/2/cv")

    assert result == {"status": "ok", "found": True, "data": {"col_0": "Bìa mới", "col_1": "31/08/2006"}}


def test_folder_path_is_normalized_like_the_queue(db, world):
    owner, _other, _admin, template = world
    add(db, template, owner, "p/2/cv", col_0="Bìa")

    assert cover(db, template, owner, "\\p\\2\\cv\\")["data"]["col_0"] == "Bìa"


def test_other_folders_and_sibling_prefixes_are_not_used(db, world):
    owner, _other, _admin, template = world
    add(db, template, owner, "p/2/cv/con", col_0="Thư mục con")
    # Thêm sau cùng (mới nhất): nếu "cv2" bị coi là con của "cv" thì sẽ được chọn nhầm.
    add(db, template, owner, "p/3/cv", col_0="Dự án khác")
    add(db, template, owner, "p/2/cv2", col_0="Hồ sơ khác cùng tiền tố")

    assert cover(db, template, owner, "p/2/cv")["data"]["col_0"] == "Thư mục con"
    assert cover(db, template, owner, "p/2/khac") == {"status": "ok", "found": False, "data": {}}


def test_underscore_and_percent_in_folder_names_are_literal(db, world):
    owner, _other, _admin, template = world
    template.config_json = json.dumps({"cover_cols": [1], "cover_folder_level": 2})
    db.commit()
    add(db, template, owner, "p/2/aXb/01", col_0="Không được khớp a_b")
    add(db, template, owner, "p/2/a%b/01", col_0="Không được khớp a%b")

    assert cover(db, template, owner, "p/2/a_b/02")["found"] is False
    add(db, template, owner, "p/2/a_b/01", col_0="Bìa thư mục cha a_b")
    assert cover(db, template, owner, "p/2/a_b/02")["data"] == {"col_0": "Bìa thư mục cha a_b"}


def test_staff_only_read_their_own_records_admin_reads_all(db, world):
    owner, other, admin, template = world
    add(db, template, other, "p/2/cv", col_0="Của người khác")

    assert cover(db, template, owner, "p/2/cv")["found"] is False
    assert cover(db, template, admin, "p/2/cv")["data"]["col_0"] == "Của người khác"


@pytest.mark.parametrize("config", [None, {"cover_cols": [], "cover_folder_level": 1}])
def test_template_without_cover_columns_returns_nothing(db, world, config):
    owner, _other, _admin, template = world
    template.config_json = json.dumps(config) if config else None
    db.commit()
    add(db, template, owner, "p/2/cv", col_0="Bìa")

    assert cover(db, template, owner, "p/2/cv") == {"status": "ok", "found": False, "data": {}}


@pytest.mark.parametrize("folder", ["", "__NO_FOLDER__"])
def test_record_without_folder_returns_nothing(db, world, folder):
    owner, _other, _admin, template = world
    add(db, template, owner, None, col_0="Bìa")

    assert cover(db, template, owner, folder)["found"] is False


def test_sync_updates_cover_columns_in_the_same_scope_only(db, world):
    owner, _other, _admin, template = world
    same = add(db, template, owner, "p/2/cv", col_0="Cũ", col_1="x", col_4="giữ nguyên")
    nested = add(db, template, owner, "p/2/cv/con", col_0="Cũ")
    sibling = add(db, template, owner, "p/2/cv2", col_0="Cũ")
    saved = add(db, template, owner, "p/2/cv", col_0="Mới", col_1="y")

    SubmissionService.sync_cover_data(saved, template.id, {"col_0": "Mới", "col_1": "y"}, db)
    db.commit()

    def data(sub):
        db.refresh(sub)
        return json.loads(sub.data_json)

    assert data(same) == {"col_0": "Mới", "col_1": "y", "col_4": "giữ nguyên"}
    assert data(nested)["col_0"] == "Mới"
    assert data(sibling) == {"col_0": "Cũ"}


def test_sync_with_level_two_reaches_sibling_folders_under_the_parent(db, world):
    owner, _other, _admin, template = world
    template.config_json = json.dumps({"cover_cols": [1], "cover_folder_level": 2})
    db.commit()
    sibling = add(db, template, owner, "p/2/hop1/hs2", col_0="Cũ")
    outside = add(db, template, owner, "p/2/hop2/hs1", col_0="Cũ")
    saved = add(db, template, owner, "p/2/hop1/hs1", col_0="Mới")

    SubmissionService.sync_cover_data(saved, template.id, {"col_0": "Mới"}, db)
    db.commit()
    db.refresh(sibling)
    db.refresh(outside)

    assert json.loads(sibling.data_json)["col_0"] == "Mới"
    assert json.loads(outside.data_json)["col_0"] == "Cũ"
