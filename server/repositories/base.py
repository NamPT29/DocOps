from typing import Generic, TypeVar

from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Small shared base that keeps persistence operations behind one boundary."""

    model: type[ModelT]

    def __init__(self, session: Session):
        self.session = session

    def get(self, entity_id: int) -> ModelT | None:
        return self.session.query(self.model).filter(self.model.id == entity_id).first()

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)

    def flush(self) -> None:
        self.session.flush()
