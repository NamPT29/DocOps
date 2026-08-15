from server.models import Dictionary, DictionaryItem
from server.repositories.base import BaseRepository


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
        return options
