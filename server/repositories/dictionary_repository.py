from sqlalchemy import event
from cachetools import TTLCache
from threading import RLock

from server.models import Dictionary, DictionaryItem
from server.repositories.base import BaseRepository
from server.settings import settings


_OPTION_MAP_CACHE = TTLCache(
    maxsize=100,
    ttl=settings.dictionary_cache_ttl_seconds,
)
_OPTION_MAP_CACHE_LOCK = RLock()


def _copy_option_map(options: dict[str, list[str]]) -> dict[str, list[str]]:
    return {name: list(values) for name, values in options.items()}

def _invalidate_cache(mapper, connection, target):
    del mapper, connection
    with _OPTION_MAP_CACHE_LOCK:
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

    def paginate_items(
        self,
        dictionary_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[DictionaryItem], int, int, int]:
        query = self.session.query(DictionaryItem).filter(
            DictionaryItem.dictionary_id == dictionary_id
        )
        total = query.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        rows = query.order_by(DictionaryItem.id).offset(
            (current_page - 1) * page_size
        ).limit(page_size).all()
        return rows, total, total_pages, current_page

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
        with _OPTION_MAP_CACHE_LOCK:
            cached = _OPTION_MAP_CACHE.get(template_id)
            if cached is not None:
                return _copy_option_map(cached)

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
            
        with _OPTION_MAP_CACHE_LOCK:
            _OPTION_MAP_CACHE[template_id] = _copy_option_map(options)
        return _copy_option_map(options)

    def fresh_option_map_for_template(self, template_id: int) -> dict[str, list[str]]:
        """Read current options from the database, bypassing worker-local cache."""
        rows = self.session.query(Dictionary, DictionaryItem).outerjoin(
            DictionaryItem,
            DictionaryItem.dictionary_id == Dictionary.id,
        ).filter(
            Dictionary.template_id == template_id
        ).order_by(Dictionary.id, DictionaryItem.id).all()

        options: dict[str, list[str]] = {}
        for dictionary, item in rows:
            values = options.setdefault(dictionary.name, [])
            if item is not None:
                values.append(
                    f"{item.code} - {item.value}" if item.code else item.value
                )
        return options
