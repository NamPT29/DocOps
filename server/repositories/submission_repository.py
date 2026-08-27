from datetime import datetime

from sqlalchemy import and_, func, or_

from server.models import (
    ProjectCase,
    ProjectDocumentAsset,
    Submission,
    Template,
    User,
)
from server.repositories.base import BaseRepository
from server.repositories.submission_query_helpers import (
    DUPLICATE_REPORT_STATUSES as _DUPLICATE_REPORT_STATUSES,
    duplicate_document_ids_query,
)
from server.utils.folder_utils import folder_path_key, normalize_folder_path


class SubmissionRepository(BaseRepository[Submission]):
    model = Submission

    def active_input_user_id(self, submission: Submission) -> int | None:
        """Return the current case assignee without rewriting the original author."""
        if submission.assigned_document_id is not None:
            row = (
                self.session.query(ProjectCase.assigned_input_user_id)
                .join(
                    ProjectDocumentAsset,
                    ProjectDocumentAsset.case_id == ProjectCase.id,
                )
                .filter(
                    ProjectDocumentAsset.assigned_document_id
                    == submission.assigned_document_id
                )
                .first()
            )
            if row is not None:
                return row[0]
        return submission.created_by_user_id

    def is_active_input_assignee(
        self,
        submission: Submission,
        user_id: int,
    ) -> bool:
        return self.active_input_user_id(submission) == user_id

    def active_input_user_ids(
        self,
        submissions: list[Submission],
    ) -> dict[int, int | None]:
        """Resolve current input ownership for a batch in one query.

        A project-case assignment, including an explicit ``NULL`` assignment,
        takes precedence over the report's original author just like
        :meth:`active_input_user_id`.
        """
        result = {
            submission.id: submission.created_by_user_id
            for submission in submissions
        }
        document_ids = {
            submission.assigned_document_id
            for submission in submissions
            if submission.assigned_document_id is not None
        }
        if not document_ids:
            return result

        assignee_by_document = dict(
            self.session.query(
                ProjectDocumentAsset.assigned_document_id,
                ProjectCase.assigned_input_user_id,
            ).join(
                ProjectCase,
                ProjectCase.id == ProjectDocumentAsset.case_id,
            ).filter(
                ProjectDocumentAsset.assigned_document_id.in_(document_ids),
            ).all()
        )
        for submission in submissions:
            document_id = submission.assigned_document_id
            if document_id in assignee_by_document:
                result[submission.id] = assignee_by_document[document_id]
        return result

    def paginate_for_input_user(
        self,
        *,
        user_id: int,
        status: str | None,
        template_id: int | None,
        start_date: str | None,
        end_date: str | None,
        folder_path: str | None,
        page: int,
        page_size: int,
        duplicate_only: bool = False,
    ) -> tuple[list[Submission], int, int, int]:
        """Paginate reports owned by a user's current project assignment."""
        query = self._apply_filters(
            self.session.query(Submission),
            owner_id=None,
            status=status,
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            folder_path=folder_path,
            duplicate_only=duplicate_only,
        )
        query = query.outerjoin(
            ProjectDocumentAsset,
            ProjectDocumentAsset.assigned_document_id
            == Submission.assigned_document_id,
        ).outerjoin(
            ProjectCase,
            ProjectCase.id == ProjectDocumentAsset.case_id,
        )
        query = query.filter(or_(
            ProjectCase.assigned_input_user_id == user_id,
            and_(
                ProjectDocumentAsset.id.is_(None),
                Submission.created_by_user_id == user_id,
            ),
        ))
        total = query.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        rows = query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        ).offset(
            (current_page - 1) * page_size
        ).limit(page_size).all()
        return rows, total, total_pages, current_page

    def list_by_ids(self, submission_ids: list[int]) -> list[Submission]:
        if not submission_ids:
            return []
        return self.session.query(Submission).filter(
            Submission.id.in_(submission_ids)
        ).all()

    def list_exact_duplicate_candidates(
        self,
        *,
        template_id: int | None,
        folder_path_key_value: str | None,
        exclude_submission_id: int,
    ) -> list[Submission]:
        query = self.session.query(Submission).filter(
            Submission.id != exclude_submission_id,
            Submission.folder_path_key == folder_path_key_value,
            Submission.status.in_(_DUPLICATE_REPORT_STATUSES),
        )
        if template_id is None:
            query = query.filter(Submission.template_id.is_(None))
        else:
            query = query.filter(Submission.template_id == template_id)
        return query.all()

    def exact_duplicate_candidates_by_scope(
        self,
        scopes: set[tuple[int | None, str | None]],
        *,
        exclude_submission_ids: set[int] | None = None,
    ) -> dict[tuple[int | None, str | None], list[Submission]]:
        """Load duplicate candidates for several template/folder scopes."""
        if not scopes:
            return {}
        scope_filters = []
        for template_id, folder_key in scopes:
            scope_filters.append(and_(
                Submission.template_id.is_(None)
                if template_id is None
                else Submission.template_id == template_id,
                Submission.folder_path_key.is_(None)
                if folder_key is None
                else Submission.folder_path_key == folder_key,
            ))
        query = self.session.query(Submission).filter(
            Submission.status.in_(_DUPLICATE_REPORT_STATUSES),
            or_(*scope_filters),
        )
        if exclude_submission_ids:
            query = query.filter(Submission.id.notin_(exclude_submission_ids))
        result = {scope: [] for scope in scopes}
        for submission in query.all():
            result.setdefault(
                (submission.template_id, submission.folder_path_key),
                [],
            ).append(submission)
        return result

    def list_user_drafts(self, user_id: int) -> list[Submission]:
        return self.session.query(Submission).filter(
            Submission.created_by_user_id == user_id,
            Submission.status == "draft",
        ).all()

    def list_by_template_id(self, template_id: int) -> list[Submission]:
        return self.session.query(Submission).filter(
            Submission.template_id == template_id
        ).all()

    def list_assignment_submission_references(
        self,
        document_ids: set[int],
        folder_paths: set[str],
    ) -> list[tuple]:
        if not document_ids:
            return []
        filters = [Submission.assigned_document_id.in_(document_ids)]
        if folder_paths:
            filters.append(Submission.folder_path.in_(folder_paths))
        return self.session.query(
            Submission.assigned_document_id,
            Submission.folder_path,
        ).filter(or_(*filters)).all()

    def list_active_reviews(self) -> list[Submission]:
        return self.session.query(Submission).filter(
            Submission.status == "pending_review"
        ).all()

    def list_active_review_submissions(
        self,
        *,
        template_id: int | None = None,
        folder_path: str | None = None,
    ) -> list[Submission]:
        query = self._apply_filters(
            self.session.query(Submission),
            status='pending_review',
            template_id=template_id,
            folder_path=folder_path,
        )
        return query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        ).all()

    def list_active_review_submission_rows(
        self,
        *,
        template_id: int | None = None,
        folder_path: str | None = None,
        duplicate_only: bool = False,
    ) -> list[tuple]:
        query = self._apply_filters(
            self.session.query(
                Submission.id,
                Submission.folder_path,
                Submission.assigned_document_id,
                Submission.created_by_user_id,
                Submission.template_id,
            ),
            status='pending_review',
            template_id=template_id,
            folder_path=folder_path,
            duplicate_only=duplicate_only,
        )
        return query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        ).all()

    def _apply_filters(
        self,
        query,
        *,
        owner_id: int | None = None,
        status: str | None = None,
        template_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        folder_path: str | None = None,
        duplicate_only: bool = False,
    ):
        if owner_id is not None:
            query = query.filter(Submission.created_by_user_id == owner_id)
        if status:
            statuses = status.split(",")
            query = query.filter(
                Submission.status.in_(statuses)
                if len(statuses) > 1
                else Submission.status == statuses[0]
            )
        if template_id:
            query = query.filter(Submission.template_id == template_id)
        if start_date:
            query = query.filter(Submission.created_at >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(Submission.created_at <= datetime.fromisoformat(end_date))
        if folder_path is not None:
            normalized = normalize_folder_path(folder_path)
            if not normalized or normalized == "__NO_FOLDER__":
                query = query.filter(
                    Submission.folder_path_key == folder_path_key(None),
                    Submission.folder_path.is_(None),
                )
            else:
                query = query.filter(
                    Submission.folder_path_key == folder_path_key(normalized),
                    Submission.folder_path == normalized,
                )
        if duplicate_only:
            query = query.filter(
                Submission.assigned_document_id.in_(
                    duplicate_document_ids_query(self.session)
                )
            )
        return query

    def paginate(
        self,
        *,
        owner_id: int | None,
        status: str | None,
        template_id: int | None,
        start_date: str | None,
        end_date: str | None,
        folder_path: str | None,
        page: int,
        page_size: int,
        duplicate_only: bool = False,
    ) -> tuple[list[Submission], int, int, int]:
        query = self._apply_filters(
            self.session.query(Submission),
            owner_id=owner_id,
            status=status,
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            folder_path=folder_path,
            duplicate_only=duplicate_only,
        )
        total = query.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        rows = query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        ).offset(
            (current_page - 1) * page_size
        ).limit(page_size).all()
        return rows, total, total_pages, current_page

    def completed_folder_groups(
        self,
        *,
        template_id: int | None,
        start_date: str | None,
        end_date: str | None,
        duplicate_only: bool = False,
    ) -> tuple[list[tuple], list[tuple], list[tuple]]:
        query = self._apply_filters(
            self.session.query(Submission),
            status="completed",
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            duplicate_only=duplicate_only,
        )
        counts = query.with_entities(
            Submission.folder_path,
            Submission.folder_path_key,
            func.count(Submission.id),
        ).group_by(
            Submission.folder_path,
            Submission.folder_path_key,
        ).all()
        inputs = query.with_entities(
            Submission.folder_path,
            Submission.folder_path_key,
            User.username,
        ).outerjoin(
            User,
            User.id == Submission.created_by_user_id,
        ).distinct().all()
        templates = query.with_entities(
            Submission.folder_path,
            Submission.folder_path_key,
            Template.name,
        ).outerjoin(
            Template,
            Template.id == Submission.template_id,
        ).distinct().all()
        return counts, inputs, templates

    def approved_for_export(
        self,
        *,
        template_id: int,
        folder_path: str | None,
        start_date: str | None,
        end_date: str | None,
        include_pending_review: bool = False,
    ) -> list[Submission]:
        query = self._apply_filters(
            self.session.query(Submission),
            status=(
                "pending_review,pending_input_confirmation,completed"
                if include_pending_review
                else "completed"
            ),
            template_id=template_id,
            folder_path=folder_path,
            start_date=start_date,
            end_date=end_date,
        )
        return query.order_by(Submission.id).all()

    def has_missing_metadata(self) -> bool:
        return self.session.query(Submission.id).filter(
            Submission.folder_path_key.is_(None)
        ).first() is not None

    def missing_metadata_batch(self, last_id: int, batch_size: int) -> list[Submission]:
        return self.session.query(Submission).filter(
            Submission.id > last_id,
            Submission.folder_path_key.is_(None),
        ).order_by(Submission.id).limit(batch_size).all()

    def latest_legacy_pdf_submission(
        self,
        safe_filename: str,
        user_id: int | None,
    ) -> Submission | None:
        query = self.session.query(Submission).filter(
            Submission.data_json.contains(safe_filename)
        )
        if user_id is not None:
            query = query.filter(Submission.created_by_user_id == user_id)
        return query.order_by(Submission.id.desc()).first()

    def delete(self, submission: Submission):
        self.session.delete(submission)

    def user_submission_status_counts(self) -> dict[int, dict[str, int]]:
        from sqlalchemy import func
        submission_rows = (
            self.session.query(
                Submission.created_by_user_id,
                Submission.status,
                func.count(Submission.id),
            )
            .group_by(Submission.created_by_user_id, Submission.status)
            .all()
        )
        submission_counts = {}
        for user_id, status, count in submission_rows:
            submission_counts.setdefault(user_id, {})[status] = count
        return submission_counts

    def count_by_document_id(self, document_id: int) -> int:
        return self.session.query(Submission).filter(
            Submission.assigned_document_id == document_id,
        ).count()

    def counts_by_document_ids(self, document_ids: set[int]) -> dict[int, int]:
        if not document_ids:
            return {}
        rows = self.session.query(
            Submission.assigned_document_id,
            func.count(Submission.id),
        ).filter(
            Submission.assigned_document_id.in_(document_ids),
        ).group_by(
            Submission.assigned_document_id,
        ).all()
        return {document_id: count for document_id, count in rows}
