from server.models import Template, User
from server.repositories.base import BaseRepository


class LookupRepository(BaseRepository[User]):
    """Read-only lookups shared by submission/document workflows."""

    model = User

    def user_exists(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return self.session.query(User.id).filter(User.id == user_id).first() is not None

    def existing_user_ids(self, user_ids: set[int]) -> set[int]:
        if not user_ids:
            return set()
        return {
            user_id
            for user_id, in self.session.query(User.id).filter(User.id.in_(user_ids)).all()
        }

    def username_map(self, user_ids: set[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        return {
            user.id: user.username
            for user in self.session.query(User).filter(User.id.in_(user_ids)).all()
        }

    def template_name_map(self, template_ids: set[int]) -> dict[int, str]:
        if not template_ids:
            return {}
        return {
            template.id: template.name
            for template in self.session.query(Template).filter(
                Template.id.in_(template_ids)
            ).all()
        }

    def get_template(self, template_id: int) -> Template | None:
        return self.session.query(Template).filter(Template.id == template_id).first()
