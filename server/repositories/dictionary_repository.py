from sqlalchemy import event
from cachetools import TTLCache

from server.models import Dictionary, DictionaryItem
from server.repositories.base import BaseRepository


_OPTION_MAP_CACHE = TTLCache(maxsize=100, ttl=3600)

def _invalidate_cache(mapper, connection, target):
    if isinstance(target, Dictionary):
        _OPTION_MAP_CACHE.pop(target.template_id, None)
    elif isinstance(target, DictionaryItem):
        _OPTION_MAP_CACHE.clear()

event.listen(Dictionary, 'after_insert', _invalidate_cache)
event.listen(Dictionary, 'after_update', _invalidate_cache)
event.listen(Dictionary, 'after_delete', _invalidate_cache)
event.listen(DictionaryItem, 'after_insert', _invalidate_cache)
event.listen(DictionaryItem, 'after_update', _invalidate_cache)
event.listen(DictionaryItem, 'after_delete', _invalidate_cache)

class DictionaryRepository(BaseRepository[Dictionary]):
    model = Dictionary

    def list_for_template(self, template_id: int) -> list[Dictionary]:
        return self.session.query(Dictionary).filter(
            Dictionary.template_id == template_id
        ).all()

    def find_for_template(self, template_id: int, name: str) -> Dictionary | None:
        return self.session.query(Dictionary).filter(
            Dictionary.template_id == template_id,
            Dictionary.name == name,
        ).first()

    def get_for_template(self, dictionary_id: int, template_id: int) -> Dictionary | None:
        return self.session.query(Dictionary).filter(
            Dictionary.id == dictionary_id,
            Dictionary.template_id == template_id,
        ).first()

    def get_dictionary(self, dictionary_id: int) -> Dictionary | None:
        return self.session.query(Dictionary).filter(
            Dictionary.id == dictionary_id
        ).first()

    def list_items(self, dictionary_id: int) -> list[DictionaryItem]:
        return self.session.query(DictionaryItem).filter(
            DictionaryItem.dictionary_id == dictionary_id
        ).order_by(DictionaryItem.id).all()

    def get_item(self, item_id: int) -> DictionaryItem | None:
        return self.session.query(DictionaryItem).filter(
            DictionaryItem.id == item_id
        ).first()

    def add_item(self, item: DictionaryItem) -> DictionaryItem:
        self.session.add(item)
        return item

    def delete_item(self, item: DictionaryItem) -> None:
        self.session.delete(item)

    def option_map_for_template(self, template_id: int) -> dict[str, list[str]]:
        if template_id in _OPTION_MAP_CACHE:
            return _OPTION_MAP_CACHE[template_id]

        rows = self.session.query(Dictionary, DictionaryItem).outerjoin(
            DictionaryItem,
            DictionaryItem.dictionary_id == Dictionary.id,
        ).filter(
            Dictionary.template_id == template_id
        ).order_by(Dictionary.id, DictionaryItem.id).all()
        
        options: dict[str, list[str]] = {}
        for dictionary, item in rows:
            values = options.setdefault(dictionary.name, [])
            if item is None:
                continue
            values.append(
                f"{item.code} - {item.value}" if item.code else item.value
            )
            
        _OPTION_MAP_CACHE[template_id] = options
        return options
