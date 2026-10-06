from sqlalchemy import func, cast, Integer
from server.models import (
    ProjectDocumentAsset,
    Submission,
    SubmissionQualityAssessment,
    ProjectReportUnit,
)
from server.models_entry_qc import CaseEntryQcResult, CaseEntryQcSampling, CaseEntryQcSampleItem
from server.repositories.workflow_repository import WorkflowRepository


class EntryQcRepository:
    def __init__(self, session):
        self.session = session

    def get_progress(self, project_id, case_id):
        repo = WorkflowRepository(self.session)
        progress = repo.entry_progress_by_case(project_id, case_id)
        return progress.get(case_id, {
            "report_total": 0,
            "reports_entered": 0,
            "submissions_total": 0,
            "submissions_under_review": 0,
            "submissions_completed": 0,
        })

    def get_quality_stats(self, project_id, case_id):
        row = (
            self.session.query(
                func.count(SubmissionQualityAssessment.submission_id).label("reports_assessed"),
                func.sum(cast(SubmissionQualityAssessment.is_error_report, Integer)).label("error_reports"),
                func.sum(SubmissionQualityAssessment.visible_field_count).label("total_fields"),
                func.sum(SubmissionQualityAssessment.changed_field_count).label("error_fields"),
            )
            .select_from(ProjectDocumentAsset)
            .join(Submission, Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id)
            .join(SubmissionQualityAssessment, SubmissionQualityAssessment.submission_id == Submission.id)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.case_id == case_id
            )
            .first()
        )
        return {
            "reports_assessed": int(row.reports_assessed or 0),
            "error_reports": int(row.error_reports or 0),
            "total_fields": int(row.total_fields or 0),
            "error_fields": int(row.error_fields or 0),
        }

    def get_rounds(self, case_id):
        return (
            self.session.query(CaseEntryQcResult)
            .filter(CaseEntryQcResult.case_id == case_id)
            .order_by(CaseEntryQcResult.round)
            .all()
        )

    def add_round(self, row: CaseEntryQcResult) -> CaseEntryQcResult:
        self.session.add(row)
        return row

    def has_submission_by_user(self, project_id, case_id, user_id) -> bool:
        row = (
            self.session.query(Submission.id)
            .join(ProjectDocumentAsset, ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.case_id == case_id,
                Submission.created_by_user_id == user_id
            )
            .first()
        )
        return row is not None

    def get_completed_submissions(self, project_id, case_id):
        return (
            self.session.query(Submission)
            .join(ProjectDocumentAsset, ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.case_id == case_id,
                Submission.status == 'completed'
            )
            .order_by(Submission.id)
            .all()
        )

    def add_sampling(self, sampling: CaseEntryQcSampling) -> CaseEntryQcSampling:
        self.session.add(sampling)
        return sampling

    def add_sample_items(self, items: list[CaseEntryQcSampleItem]):
        self.session.add_all(items)

    def get_sampling(self, case_id: int, round_num: int) -> CaseEntryQcSampling | None:
        return (
            self.session.query(CaseEntryQcSampling)
            .filter(
                CaseEntryQcSampling.case_id == case_id,
                CaseEntryQcSampling.round == round_num
            )
            .first()
        )

    def get_sample_items_with_info(self, sampling_id: int):
        return (
            self.session.query(
                CaseEntryQcSampleItem,
                ProjectReportUnit.display_name.label("report_name")
            )
            .join(Submission, Submission.id == CaseEntryQcSampleItem.submission_id)
            .join(ProjectDocumentAsset, ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id)
            .join(ProjectReportUnit, ProjectReportUnit.id == ProjectDocumentAsset.report_unit_id)
            .filter(CaseEntryQcSampleItem.sampling_id == sampling_id)
            .order_by(CaseEntryQcSampleItem.id)
            .all()
        )

