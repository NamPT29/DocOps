from server.models import Template
from server.repositories.base import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    model = Template

    def get_by_filename(self, filename: str) -> Template | None:
        return self.session.query(Template).filter(
            Template.filename == filename
        ).first()

    def list_active(self) -> list[Template]:
        return self.session.query(Template).filter(
            Template.is_active.is_(True)
        ).all()

    def lock_for_update(self, template_id: int) -> None:
        self.session.query(Template.id).filter(
            Template.id == template_id,
        ).with_for_update().first()
