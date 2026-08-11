import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Dictionary, DictionaryItem, Template
from server.routers.dictionaries import (
    BulkDictionaryItemsRequest,
    _parse_bulk_dictionary_items,
    bulk_import_dictionary_items,
    get_dictionaries,
)


@pytest.fixture
def dictionary_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _create_template_dictionary(db, template_name):
    template = Template(name=template_name, filename=f'{template_name}.xlsx')
    db.add(template)
    db.flush()
    dictionary = Dictionary(
        template_id=template.id,
        name='DM_DanToc',
        description='Dân tộc',
    )
    db.add(dictionary)
    db.commit()
    return template, dictionary


def test_each_template_has_an_isolated_dictionary_store(dictionary_db):
    template_a, dictionary_a = _create_template_dictionary(dictionary_db, 'Mẫu A')
    template_b, dictionary_b = _create_template_dictionary(dictionary_db, 'Mẫu B')

    result_a = get_dictionaries(template_a.id, db=dictionary_db)
    result_b = get_dictionaries(template_b.id, db=dictionary_db)

    assert [item['id'] for item in result_a['data']] == [dictionary_a.id]
    assert [item['id'] for item in result_b['data']] == [dictionary_b.id]

    with pytest.raises(HTTPException, match='không thuộc biểu mẫu') as error:
        bulk_import_dictionary_items(
            template_a.id,
            dictionary_b.id,
            BulkDictionaryItemsRequest(text='01 - Kinh'),
            current_user={'role': 'admin'},
            db=dictionary_db,
        )
    assert error.value.status_code == 404


def test_bulk_import_preserves_leading_zero_and_supports_skip_and_update(dictionary_db):
    template, dictionary = _create_template_dictionary(dictionary_db, 'Mẫu C')
    dictionary_db.add(DictionaryItem(dictionary_id=dictionary.id, code='01', value='Cũ'))
    dictionary_db.commit()

    skipped = bulk_import_dictionary_items(
        template.id,
        dictionary.id,
        BulkDictionaryItemsRequest(
            text='01 - Kinh mới\n02 - Tày\nA-03 - Giá trị - có gạch nối',
            duplicate_mode='skip',
        ),
        current_user={'role': 'admin'},
        db=dictionary_db,
    )

    assert skipped['data'] == {
        'dictionary_id': dictionary.id,
        'template_id': template.id,
        'parsed': 3,
        'added': 2,
        'updated': 0,
        'skipped': 1,
    }
    stored = {
        item.code: item.value
        for item in dictionary_db.query(DictionaryItem)
        .filter(DictionaryItem.dictionary_id == dictionary.id)
        .all()
    }
    assert stored == {
        '01': 'Cũ',
        '02': 'Tày',
        'A-03': 'Giá trị - có gạch nối',
    }

    updated = bulk_import_dictionary_items(
        template.id,
        dictionary.id,
        BulkDictionaryItemsRequest(text='01 - Kinh mới', duplicate_mode='update'),
        current_user={'role': 'admin'},
        db=dictionary_db,
    )
    assert updated['data']['updated'] == 1
    assert dictionary_db.query(DictionaryItem).filter(
        DictionaryItem.dictionary_id == dictionary.id,
        DictionaryItem.code == '01',
    ).first().value == 'Kinh mới'


def test_bulk_parser_rejects_bad_or_duplicate_lines_atomically(dictionary_db):
    template, dictionary = _create_template_dictionary(dictionary_db, 'Mẫu D')

    with pytest.raises(HTTPException, match='cần định dạng'):
        bulk_import_dictionary_items(
            template.id,
            dictionary.id,
            BulkDictionaryItemsRequest(text='dòng không hợp lệ'),
            current_user={'role': 'admin'},
            db=dictionary_db,
        )
    assert dictionary_db.query(DictionaryItem).count() == 0

    with pytest.raises(HTTPException, match='bị trùng'):
        _parse_bulk_dictionary_items('01 - Kinh\n01 - Giá trị khác')
    assert dictionary_db.query(DictionaryItem).count() == 0


def test_bulk_parser_accepts_two_columns_copied_from_excel():
    assert _parse_bulk_dictionary_items('001\tKinh\n002\tTày') == [
        ('001', 'Kinh'),
        ('002', 'Tày'),
    ]
