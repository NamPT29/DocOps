import os
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException

from server.models import (
    AssignedDocument,
    Submission,
    SubmissionReviewAssignment,
)
from server.repositories import (
    DocumentRepository,
    LookupRepository,
    ReviewRepository,
    SubmissionRepository,
    SubmissionViewRepository,
)
from server.services.submission_helpers import COMPLETED_WITHOUT_FOLDER, _pdf_url
from server.services.submission_metadata_service import backfill_submission_metadata
from server.utils.folder_utils import normalize_folder_path

class ReviewWorkflowService:

    @staticmethod
    def get_review_assignment(db: Session, submission_id: int):
        return ReviewRepository(db).get_submission_assignment(submission_id)

    @staticmethod
    def assign_submission_reviewer(
        submission: Submission,
        db: Session,
        *,
        document: AssignedDocument | None = None,
        required: bool = True,
    ):
        review_repository = ReviewRepository(db)
        lookup_repository = LookupRepository(db)
        assignment = review_repository.get_submission_assignment(submission.id)
        if document is None and submission.assigned_document_id is not None:
            document = DocumentRepository(db).get(submission.assigned_document_id)
        document_assignment = None
        if document:
            document_assignment = review_repository.get_document_assignment(document.id)
        reviewer_id = document_assignment.reviewer_user_id if document_assignment else None
        if not reviewer_id and submission.folder_path:
            reviewer_id = review_repository.get_folder_reviewer(submission.folder_path)
            
        if reviewer_id:
            if not lookup_repository.user_exists(reviewer_id):
                reviewer_id = None
        elif assignment and assignment.reviewer_user_id != submission.created_by_user_id:
            if lookup_repository.user_exists(assignment.reviewer_user_id):
                return assignment
        if not reviewer_id or reviewer_id == submission.created_by_user_id:
            if required:
                raise HTTPException(
                    status_code=409,
                    detail="Tài liệu chưa được phân người kiểm tra phù hợp",
                )
            return None
        if assignment:
            assignment.reviewer_user_id = reviewer_id
            assignment.assigned_at = datetime.now()
        else:
            assignment = SubmissionReviewAssignment(
                submission_id=submission.id,
                reviewer_user_id=reviewer_id,
            )
            review_repository.add(assignment)
        return assignment

    @staticmethod
    def assign_submission_reviewers(
        submissions: list[Submission],
        db: Session,
        *,
        required: bool = True,
    ) -> dict[int, SubmissionReviewAssignment | None]:
        """Batch equivalent of ``assign_submission_reviewer``.

        This is intentionally used only by bulk submission so single-report
        behavior and its public contract remain unchanged.
        """
        if not submissions:
            return {}
        submission_ids = [submission.id for submission in submissions]
        review_repository = ReviewRepository(db)
        assignments = review_repository.submission_assignments_by_ids(submission_ids)
        document_ids = {
            submission.assigned_document_id
            for submission in submissions
            if submission.assigned_document_id is not None
        }
        reviewers_by_document = {
            assignment.document_id: assignment.reviewer_user_id
            for assignment in review_repository.document_assignments_by_ids(
                document_ids,
            ).values()
        }

        folder_paths = {
            submission.folder_path
            for submission in submissions
            if submission.folder_path and submission.folder_path != "__ROOT__"
        }
        reviewers_by_folder = review_repository.folder_reviewers_by_paths(folder_paths)

        candidate_by_submission: dict[int, int | None] = {}
        candidate_was_assigned: set[int] = set()
        user_ids: set[int] = set()
        for submission in submissions:
            reviewer_id = reviewers_by_document.get(submission.assigned_document_id)
            if reviewer_id is None and submission.folder_path:
                reviewer_id = reviewers_by_folder.get(submission.folder_path)
            if reviewer_id is not None:
                candidate_was_assigned.add(submission.id)
                user_ids.add(reviewer_id)
            else:
                existing = assignments.get(submission.id)
                if existing and existing.reviewer_user_id is not None:
                    user_ids.add(existing.reviewer_user_id)
            candidate_by_submission[submission.id] = reviewer_id
        valid_user_ids = LookupRepository(db).existing_user_ids(user_ids)

        result: dict[int, SubmissionReviewAssignment | None] = {}
        for submission in submissions:
            assignment = assignments.get(submission.id)
            reviewer_id = candidate_by_submission[submission.id]
            if submission.id in candidate_was_assigned:
                if reviewer_id not in valid_user_ids:
                    reviewer_id = None
            elif (
                assignment
                and assignment.reviewer_user_id != submission.created_by_user_id
                and assignment.reviewer_user_id in valid_user_ids
            ):
                result[submission.id] = assignment
                continue

            if reviewer_id is None or reviewer_id == submission.created_by_user_id:
                if required:
                    raise HTTPException(
                        status_code=409,
                        detail="Tài liệu chưa được phân người kiểm tra phù hợp",
                    )
                result[submission.id] = None
                continue
            if assignment:
                assignment.reviewer_user_id = reviewer_id
                assignment.assigned_at = datetime.now()
            else:
                assignment = SubmissionReviewAssignment(
                    submission_id=submission.id,
                    reviewer_user_id=reviewer_id,
                )
                db.add(assignment)
                assignments[submission.id] = assignment
            result[submission.id] = assignment
        return result

    @staticmethod
    def backfill_pending_review_assignments(db: Session) -> None:
        backfill_submission_metadata(db)
        review_repository = ReviewRepository(db)
        pending, assignments, document_reviewers = (
            review_repository.pending_assignment_context()
        )
        if not pending:
            return
        candidate_user_ids = set(document_reviewers.values()) | {
            assignment.reviewer_user_id
            for assignment in assignments.values()
            if assignment.reviewer_user_id is not None
        }
        valid_user_ids = LookupRepository(db).existing_user_ids(candidate_user_ids)

        changed = False
        for submission in pending:
            assignment = assignments.get(submission.id)
            reviewer_id = document_reviewers.get(submission.assigned_document_id)
            if (
                reviewer_id not in valid_user_ids
                or reviewer_id == submission.created_by_user_id
            ):
                reviewer_id = None
            if reviewer_id is None and assignment:
                existing_reviewer_id = assignment.reviewer_user_id
                if (
                    existing_reviewer_id in valid_user_ids
                    and existing_reviewer_id != submission.created_by_user_id
                ):
                    continue
            if reviewer_id is None:
                continue
            if assignment:
                if assignment.reviewer_user_id == reviewer_id:
                    continue
                assignment.reviewer_user_id = reviewer_id
                assignment.assigned_at = datetime.now()
            else:
                assignment = SubmissionReviewAssignment(
                    submission_id=submission.id,
                    reviewer_user_id=reviewer_id,
                )
                review_repository.add(assignment)
                assignments[submission.id] = assignment
            changed = True
        if changed:
            db.commit()

    @staticmethod
    def can_review_submission(submission: Submission, current_user: dict, db: Session) -> bool:
        if current_user.get('role') == 'admin':
            return True
        assignment = ReviewWorkflowService.get_review_assignment(db, submission.id)
        if (
            assignment
            and assignment.reviewer_user_id == current_user["id"]
            and submission.created_by_user_id != current_user["id"]
        ):
            return True
        if submission.status != "pending_review":
            return False
        assignment = ReviewWorkflowService.assign_submission_reviewer(
            submission,
            db,
            required=False,
        )
        return bool(
            assignment
            and assignment.reviewer_user_id == current_user["id"]
            and submission.created_by_user_id != current_user["id"]
        )

    @staticmethod
    def require_assigned_reviewer(
        submission: Submission,
        current_user: dict,
        db: Session,
    ) -> SubmissionReviewAssignment:
        if current_user.get('role') == 'admin':
            return ReviewWorkflowService.get_review_assignment(db, submission.id)
        assignment = ReviewWorkflowService.get_review_assignment(db, submission.id)
        if submission.status == "pending_review":
            assignment = ReviewWorkflowService.assign_submission_reviewer(
                submission,
                db,
                required=False,
            )
        if (
            not assignment
            or assignment.reviewer_user_id != current_user["id"]
            or submission.created_by_user_id == current_user["id"]
        ):
            raise HTTPException(status_code=403, detail="Hồ sơ không được phân cho bạn kiểm tra")
        return assignment

    @staticmethod
    def review_submission_payload(
        submission: Submission,
        document_metadata: dict | None,
        user_map: dict[int, str],
        template_map: dict[int, str],
        viewer_map: dict[int, dict] | None = None,
    ) -> dict:
        data_dict = json.loads(submission.data_json)
        viewer = (viewer_map or {}).get(submission.id)
        if document_metadata:
            document = document_metadata["document"]
            data_dict["_pdf_filename"] = document.original_filename
            data_dict["_pdf_uuid"] = document.uuid_filename
            data_dict["_pdf_url"] = _pdf_url(document.uuid_filename)
            if document_metadata["relative_path"]:
                data_dict["_pdf_relative_path"] = document_metadata["relative_path"]
        elif data_dict.get("_pdf_uuid"):
            uuid_filename = os.path.basename(str(data_dict["_pdf_uuid"]))
            data_dict["_pdf_uuid"] = uuid_filename
            data_dict["_pdf_url"] = _pdf_url(uuid_filename)
        folder_path = normalize_folder_path(submission.folder_path)
        return {
            'viewing_user_id': viewer.get('user_id') if viewer else None,
            'viewing_user_name': viewer.get('username') if viewer else None,
            'is_being_viewed': bool(viewer),
            "id": submission.id,
            "ho_ten": data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)",
            "so_giay_to": data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)",
            "created_at": (submission.created_at + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S") if submission.created_at else "",
            "template": template_map.get(submission.template_id, "Unknown") if submission.template_id else "Unknown",
            "template_id": submission.template_id,
            "pdf_filename": data_dict.get("_pdf_filename", ""),
            "pdf_relative_path": data_dict.get("_pdf_relative_path", ""),
            "folder_path": folder_path,
            "folder_name": folder_path.rstrip("/").rsplit("/", 1)[-1] if folder_path else "",
            "is_checked": submission.is_checked,
            "status": submission.status,
            "has_errors": bool(data_dict.get("_wrong_sections", [])),
            "creator_name": user_map.get(submission.created_by_user_id, "Unknown"),
        }

    @staticmethod
    def get_admin_review_folder_groups(
        db: Session,
        template_id: int | None,
        duplicate_only: bool = False,
    ) -> list[dict]:
        submissions = SubmissionRepository(db).list_active_review_submission_rows(
            template_id=template_id,
            duplicate_only=duplicate_only,
        )
        user_ids = {
            created_by_user_id
            for _, _, _, created_by_user_id, _ in submissions
            if created_by_user_id is not None
        }
        template_ids = {
            template_id
            for _, _, _, _, template_id in submissions
            if template_id is not None
        }
        lookup_repository = LookupRepository(db)
        user_map = lookup_repository.username_map(user_ids)
        template_map = lookup_repository.template_name_map(template_ids)
        groups: dict[str, dict] = {}
        for submission_id, folder_path, assigned_document_id, created_by_user_id, template_id in submissions:
            folder_path = normalize_folder_path(folder_path) or COMPLETED_WITHOUT_FOLDER
            group = groups.setdefault(
                folder_path,
                {
                    'folder_path': folder_path,
                    'folder_name': (
                        'Chưa xác định folder'
                        if folder_path == COMPLETED_WITHOUT_FOLDER
                        else 'Thư mục gốc'
                        if folder_path == '__ROOT__'
                        else folder_path.rstrip('/').rsplit('/', 1)[-1]
                    ),
                    'submitted_count': 0,
                    'document_keys': set(),
                    'input_names': set(),
                    'template_names': set(),
                },
            )
            group['submitted_count'] += 1
            group['document_keys'].add(
                assigned_document_id or f'submission:{submission_id}'
            )
            group['input_names'].add(
                user_map.get(created_by_user_id, 'Unknown')
            )
            group['template_names'].add(
                template_map.get(template_id, 'Unknown')
            )

        result = []
        for folder_path in sorted(groups, key=str.casefold):
            group = groups[folder_path]
            group['total_documents'] = len(group.pop('document_keys'))
            group['input_names'] = sorted(group['input_names'], key=str.casefold)
            group['template_names'] = sorted(group['template_names'], key=str.casefold)
            result.append(group)
        return result
