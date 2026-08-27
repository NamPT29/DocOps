from server.models import (
    Project,
    ProjectDocumentAsset,
    SubmissionQualityAssessment,
)
from server.repositories.base import BaseRepository


class SubmissionQualityRepository(BaseRepository[SubmissionQualityAssessment]):
    model = SubmissionQualityAssessment

    def get_for_submission(self, submission_id: int) -> SubmissionQualityAssessment | None:
        for assessment in self.session.new:
            if (
                isinstance(assessment, SubmissionQualityAssessment)
                and assessment.submission_id == submission_id
            ):
                return assessment
        cache = self.session.info.get("submission_quality_assessments")
        if cache is not None and submission_id in cache:
            return cache[submission_id]
        return self.session.get(SubmissionQualityAssessment, submission_id)

    def add(self, assessment: SubmissionQualityAssessment) -> SubmissionQualityAssessment:
        cache = self.session.info.get("submission_quality_assessments")
        if cache is not None:
            cache[assessment.submission_id] = assessment
        return super().add(assessment)

    def map_for_submissions(self, submission_ids: list[int]) -> dict[int, SubmissionQualityAssessment]:
        if not submission_ids:
            return {}
        rows = self.session.query(SubmissionQualityAssessment).filter(
            SubmissionQualityAssessment.submission_id.in_(submission_ids)
        ).all()
        return {row.submission_id: row for row in rows}

    def prime_for_submissions(
        self,
        submission_ids: list[int],
    ) -> dict[int, SubmissionQualityAssessment | None]:
        """Cache both present and absent assessments for baseline creation."""
        if not submission_ids:
            return {}
        rows = self.session.query(SubmissionQualityAssessment).filter(
            SubmissionQualityAssessment.submission_id.in_(submission_ids),
        ).all()
        found = {row.submission_id: row for row in rows}
        primed = {
            submission_id: found.get(submission_id)
            for submission_id in submission_ids
        }
        cache = self.session.info.setdefault("submission_quality_assessments", {})
        cache.update(primed)
        return primed

    def project_for_document(self, assigned_document_id: int | None) -> Project | None:
        if assigned_document_id is None:
            return None
        project_cache = self.session.info.get("submission_quality_projects_by_document")
        if project_cache is not None and assigned_document_id in project_cache:
            return project_cache[assigned_document_id]
        return (
            self.session.query(Project)
            .join(
                ProjectDocumentAsset,
                ProjectDocumentAsset.project_id == Project.id,
            )
            .filter(ProjectDocumentAsset.assigned_document_id == assigned_document_id)
            .first()
        )

    def prime_projects_for_documents(self, document_ids: set[int]) -> dict[int, Project | None]:
        """Prime project lookups used by baseline creation for a bulk request."""
        if not document_ids:
            return {}
        rows = (
            self.session.query(ProjectDocumentAsset.assigned_document_id, Project)
            .join(Project, Project.id == ProjectDocumentAsset.project_id)
            .filter(ProjectDocumentAsset.assigned_document_id.in_(document_ids))
            .all()
        )
        project_map: dict[int, Project | None] = {
            document_id: None for document_id in document_ids
        }
        for document_id, project in rows:
            project_map[document_id] = project
        cache = self.session.info.setdefault(
            "submission_quality_projects_by_document",
            {},
        )
        cache.update(project_map)
        return project_map
