from typing import TypeVar

from sqlalchemy import event
from sqlalchemy.orm import Session

from server.models import Template, User
from server.repositories.base import BaseRepository


LookupModelT = TypeVar("LookupModelT", User, Template)
_LOOKUP_CACHE_KEY = "lookup_repository_entities"


@event.listens_for(Session, "after_flush")
@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
@event.listens_for(Session, "after_soft_rollback")
def _clear_lookup_cache(session: Session, *_args) -> None:
    session.info.pop(_LOOKUP_CACHE_KEY, None)


class LookupRepository(BaseRepository[User]):
    """Read-only lookups with a transaction-safe, session-local cache."""

    model = User

    def _entity_cache(self, cache_name: str) -> dict[int, object | None]:
        repository_cache = self.session.info.setdefault(_LOOKUP_CACHE_KEY, {})
        return repository_cache.setdefault(cache_name, {})

    def _invalidate_pending_lookup_changes(self) -> None:
        for collection in (self.session.new, self.session.dirty, self.session.deleted):
            if any(isinstance(entity, (User, Template)) for entity in collection):
                self.session.info.pop(_LOOKUP_CACHE_KEY, None)
                return

    def _load_entities(
        self,
        cache_name: str,
        model: type[LookupModelT],
        entity_ids: set[int],
    ) -> dict[int, LookupModelT | None]:
        requested_ids = set(entity_ids)
        if not requested_ids:
            return {}

        self._invalidate_pending_lookup_changes()
        cache = self._entity_cache(cache_name)
        missing_ids = requested_ids - set(cache)
        if missing_ids:
            rows = self.session.query(model).filter(model.id.in_(missing_ids)).all()
            # The query can autoflush pending changes, which clears the cache.
            cache = self._entity_cache(cache_name)
            found = {row.id: row for row in rows}
            for entity_id in missing_ids:
                cache[entity_id] = found.get(entity_id)
        return {entity_id: cache.get(entity_id) for entity_id in requested_ids}

    def user_exists(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return self._load_entities("users", User, {user_id})[user_id] is not None

    def existing_user_ids(self, user_ids: set[int]) -> set[int]:
        users = self._load_entities("users", User, user_ids)
        return {user_id for user_id, user in users.items() if user is not None}

    def username_map(self, user_ids: set[int]) -> dict[int, str]:
        users = self._load_entities("users", User, user_ids)
        return {
            user_id: user.username
            for user_id, user in users.items()
            if user is not None
        }

    def template_name_map(self, template_ids: set[int]) -> dict[int, str]:
        templates = self._load_entities("templates", Template, template_ids)
        return {
            template_id: template.name
            for template_id, template in templates.items()
            if template is not None
        }

    def get_template(self, template_id: int) -> Template | None:
        return self._load_entities("templates", Template, {template_id})[template_id]
