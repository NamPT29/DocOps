from collections import Counter

from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Project,
    ProjectAssignmentHistory,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectPdfDeletionAudit,
    ProjectReportUnit,
    ProjectUploadFile,
    ProjectUploadSession,
    Submission,
    SubmissionReviewAssignment,
    SubmissionViewPresence,
)


class ProjectAdminRepository:
    def __init__(self, session):
        self.session = session

    def lock_project(self, project_id):
        return self.session.query(Project).filter(
            Project.id == project_id,
        ).with_for_update().first()

    def lock_cases(self, project_id):
        return self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id,
        ).order_by(
            ProjectCase.case_key,
            ProjectCase.id,
        ).with_for_update().all()

    def member_rows(self, project_id):
        return self.session.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
        ).all()

    def set_active_members(self, project_id, *, input_user_ids, reviewer_user_ids):
        desired = {
            "input": set(input_user_ids),
            "reviewer": set(reviewer_user_ids),
        }
        existing = {
            (row.user_id, row.member_role): row
            for row in self.member_rows(project_id)
        }
        for row in existing.values():
            row.is_active = row.user_id in desired[row.member_role]
        for member_role, user_ids in desired.items():
            for user_id in user_ids:
                row = existing.get((user_id, member_role))
                if row:
                    row.is_active = True
                else:
                    self.session.add(ProjectMember(
                        project_id=project_id,
                        user_id=user_id,
                        member_role=member_role,
                        is_active=True,
                    ))

    def assignment_counts(self, cases, *, input_user_ids, reviewer_user_ids):
        input_set = set(input_user_ids)
        reviewer_set = set(reviewer_user_ids)
        input_counts = Counter(
            case_row.assigned_input_user_id
            for case_row in cases
            if case_row.assigned_input_user_id in input_set
        )
        reviewer_counts = Counter(
            case_row.assigned_reviewer_user_id
            for case_row in cases
            if case_row.assigned_reviewer_user_id in reviewer_set
        )
        return input_counts, reviewer_counts

    def submissions_for_case(self, case_id):
        return self.session.query(Submission).join(
            ProjectDocumentAsset,
            ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.case_id == case_id,
        ).order_by(Submission.id).all()

    def transfer_case_submission_owner(self, case_id, to_user_id):
        submissions = self.submissions_for_case(case_id)
        for submission in submissions:
            submission.created_by_user_id = to_user_id
        return len(submissions)

    def sync_case_submission_reviewer(self, case_id, reviewer_user_id):
        submissions = self.submissions_for_case(case_id)
        changed = 0
        for submission in submissions:
            assignment = self.session.query(SubmissionReviewAssignment).filter(
                SubmissionReviewAssignment.submission_id == submission.id,
            ).first()
            if reviewer_user_id is None:
                if assignment:
                    self.session.delete(assignment)
                    changed += 1
            elif assignment:
                if assignment.reviewer_user_id != reviewer_user_id:
                    assignment.reviewer_user_id = reviewer_user_id
                    changed += 1
            else:
                self.session.add(SubmissionReviewAssignment(
                    submission_id=submission.id,
                    reviewer_user_id=reviewer_user_id,
                ))
                changed += 1
        return changed

    def add_assignment_history(
        self,
        *,
        project_id,
        case_id,
        assignment_role,
        from_user_id,
        to_user_id,
        changed_by_user_id,
        reason,
    ):
        self.session.add(ProjectAssignmentHistory(
            project_id=project_id,
            case_id=case_id,
            assignment_role=assignment_role,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            changed_by_user_id=changed_by_user_id,
            reason=reason,
        ))

    def list_project_assets(self, project_id):
        rows = self.session.query(
            ProjectDocumentAsset,
            ProjectCase,
            ProjectReportUnit,
            AssignedDocument,
        ).join(
            ProjectCase,
            ProjectCase.id == ProjectDocumentAsset.case_id,
        ).join(
            ProjectReportUnit,
            ProjectReportUnit.id == ProjectDocumentAsset.report_unit_id,
        ).outerjoin(
            AssignedDocument,
            AssignedDocument.id == ProjectDocumentAsset.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
        ).order_by(
            ProjectCase.case_key,
            ProjectReportUnit.report_key,
            ProjectDocumentAsset.relative_path,
        ).all()
        document_ids = {
            document.id
            for _asset, _case_row, _report, document in rows
            if document is not None
        }
        submission_counts = Counter()
        if document_ids:
            for (document_id,) in self.session.query(Submission.assigned_document_id).filter(
                Submission.assigned_document_id.in_(document_ids),
            ).all():
                submission_counts[document_id] += 1
        return rows, submission_counts

    def lock_asset(self, project_id, asset_id):
        return self.session.query(ProjectDocumentAsset).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.id == asset_id,
        ).with_for_update().first()

    def submission_count_for_document(self, document_id):
        if document_id is None:
            return 0
        return self.session.query(Submission.id).filter(
            Submission.assigned_document_id == document_id,
        ).count()

    def add_pdf_deletion_audit(self, asset, deleted_by_user_id):
        self.session.add(ProjectPdfDeletionAudit(
            project_id=asset.project_id,
            case_id=asset.case_id,
            report_unit_id=asset.report_unit_id,
            relative_path=asset.relative_path,
            content_sha256=asset.content_sha256,
            deleted_by_user_id=deleted_by_user_id,
        ))

    def delete_asset_graph(self, asset):
        document_id = asset.assigned_document_id
        if document_id is not None:
            asset.assigned_document_id = None
            self.session.flush()
            self.session.query(AssignedDocumentReviewAssignment).filter(
                AssignedDocumentReviewAssignment.document_id == document_id,
            ).delete(synchronize_session=False)
            self.session.query(AssignedDocumentPath).filter(
                AssignedDocumentPath.document_id == document_id,
            ).delete(synchronize_session=False)
            self.session.query(AssignedDocumentFolder).filter(
                AssignedDocumentFolder.document_id == document_id,
            ).delete(synchronize_session=False)
            document = self.session.get(AssignedDocument, document_id)
            if document:
                self.session.delete(document)
        self.session.delete(asset)

    def project_delete_manifest(self, project_id):
        asset_rows = self.session.query(
            ProjectDocumentAsset.storage_filename,
            ProjectDocumentAsset.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
        ).all()
        session_ids = [
            row[0]
            for row in self.session.query(ProjectUploadSession.id).filter(
                ProjectUploadSession.project_id == project_id,
            ).all()
        ]
        return {
            "storage_filenames": sorted({row[0] for row in asset_rows if row[0]}),
            "assigned_document_ids": sorted({row[1] for row in asset_rows if row[1] is not None}),
            "upload_session_ids": session_ids,
        }

    def delete_project_graph(self, project, manifest):
        project_id = project.id
        document_ids = list(manifest["assigned_document_ids"])
        session_ids = list(manifest["upload_session_ids"])
        submission_ids = []
        if document_ids:
            submission_ids = [
                row[0]
                for row in self.session.query(Submission.id).filter(
                    Submission.assigned_document_id.in_(document_ids),
                ).all()
            ]

        counts = {}
        if submission_ids:
            counts["submission_view_presence"] = self.session.query(
                SubmissionViewPresence
            ).filter(
                SubmissionViewPresence.submission_id.in_(submission_ids),
            ).delete(synchronize_session=False)
            counts["submission_review_assignments"] = self.session.query(
                SubmissionReviewAssignment
            ).filter(
                SubmissionReviewAssignment.submission_id.in_(submission_ids),
            ).delete(synchronize_session=False)
        else:
            counts["submission_view_presence"] = 0
            counts["submission_review_assignments"] = 0

        if document_ids:
            counts["submissions"] = self.session.query(Submission).filter(
                Submission.assigned_document_id.in_(document_ids),
            ).delete(synchronize_session=False)
            counts["document_review_assignments"] = self.session.query(
                AssignedDocumentReviewAssignment
            ).filter(
                AssignedDocumentReviewAssignment.document_id.in_(document_ids),
            ).delete(synchronize_session=False)
            counts["document_paths"] = self.session.query(AssignedDocumentPath).filter(
                AssignedDocumentPath.document_id.in_(document_ids),
            ).delete(synchronize_session=False)
            counts["document_folders"] = self.session.query(AssignedDocumentFolder).filter(
                AssignedDocumentFolder.document_id.in_(document_ids),
            ).delete(synchronize_session=False)
        else:
            counts.update({
                "submissions": 0,
                "document_review_assignments": 0,
                "document_paths": 0,
                "document_folders": 0,
            })

        counts["pdf_deletion_audits"] = self.session.query(ProjectPdfDeletionAudit).filter(
            ProjectPdfDeletionAudit.project_id == project_id,
        ).delete(synchronize_session=False)
        counts["assignment_history"] = self.session.query(ProjectAssignmentHistory).filter(
            ProjectAssignmentHistory.project_id == project_id,
        ).delete(synchronize_session=False)
        counts["assets"] = self.session.query(ProjectDocumentAsset).filter(
            ProjectDocumentAsset.project_id == project_id,
        ).delete(synchronize_session=False)
        counts["report_units"] = self.session.query(ProjectReportUnit).filter(
            ProjectReportUnit.project_id == project_id,
        ).delete(synchronize_session=False)
        counts["cases"] = self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id,
        ).delete(synchronize_session=False)

        if session_ids:
            counts["upload_files"] = self.session.query(ProjectUploadFile).filter(
                ProjectUploadFile.session_id.in_(session_ids),
            ).delete(synchronize_session=False)
        else:
            counts["upload_files"] = 0
        counts["upload_sessions"] = self.session.query(ProjectUploadSession).filter(
            ProjectUploadSession.project_id == project_id,
        ).delete(synchronize_session=False)
        counts["members"] = self.session.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
        ).delete(synchronize_session=False)

        self.session.delete(project)
        self.session.flush()
        counts["projects"] = 1

        if document_ids:
            counts["assigned_documents"] = self.session.query(AssignedDocument).filter(
                AssignedDocument.id.in_(document_ids),
            ).delete(synchronize_session=False)
        else:
            counts["assigned_documents"] = 0
        return counts
