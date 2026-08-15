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
