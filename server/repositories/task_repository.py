from server.models import Task, Template, User
from server.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    model = Task

    def list_with_names(self, user_id: int | None) -> list[tuple]:
        query = self.session.query(Task, User.username, Template.name).outerjoin(
            User,
            User.id == Task.user_id,
        ).outerjoin(
            Template,
            Template.id == Task.template_id,
        )
        if user_id is not None:
            query = query.filter(Task.user_id == user_id)
        return query.order_by(Task.created_at.desc()).all()
