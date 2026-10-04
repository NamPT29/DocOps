from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func

from server.database import get_utc_now
from server.models import (
    CaseInputAssignment,
    CaseStageState,
    Project,
    ProjectAssignmentHistory,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
    User,
)
from server.services import account_policy_service as account_policy
from server.services.arrangement_catalog_parser import is_placeholder_box_key

NON_DRAFT_STATUSES = ("rejected", "pending_review", "pending_input_confirmation", "completed")


class ProjectAssignmentRepository:
    def __init__(self, session):
        self.session = session

    def get_project(self, project_id):
        return self.session.get(Project, project_id)

    def lock_project(self, project_id):
        return (
            self.session.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )

    def active_member_ids(self, project_id, member_role):
        rows = (
            self.session.query(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.member_role == member_role,
                ProjectMember.is_active.is_(True),
                User.is_locked.is_(False),
            )
            .order_by(User.id)
            .all()
        )
        return [
            user.id
            for user in rows
            if not account_policy.is_expired(user)
        ]

    def eligible_input_members(self, project_id: int) -> list[dict]:
        rows = (
            self.session.query(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.member_role == "input",
                ProjectMember.is_active.is_(True),
                User.is_locked.is_(False),
            )
            .order_by(User.username)
            .all()
        )
        return [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name or u.username,
                "role": u.role,
                "account_type": u.account_type,
            }
            for u in rows
            if not account_policy.is_expired(u)
        ]

    def member_ids(self, project_id: int, member_role: str) -> list[int]:
        return [
            row[0]
            for row in self.session.query(ProjectMember.user_id)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.member_role == member_role,
            )
            .all()
        ]

    def lock_cases(self, project_id):
        return (
            self.session.query(ProjectCase)
            .filter(ProjectCase.project_id == project_id)
            .order_by(ProjectCase.case_key, ProjectCase.id)
            .with_for_update()
            .all()
        )

    def lock_case_by_id(self, project_id: int, case_id: int):
        return (
            self.session.query(ProjectCase)
            .filter(
                ProjectCase.project_id == project_id,
                ProjectCase.id == case_id,
            )
            .with_for_update()
            .first()
        )

    def case_ids_with_history(self, project_id: int) -> set[int]:
        return {
            row[0]
            for row in self.session.query(CaseInputAssignment.case_id)
            .filter(CaseInputAssignment.project_id == project_id)
            .distinct()
            .all()
        }

    def active_case_input_assignment(self, case_id: int):
        return (
            self.session.query(CaseInputAssignment)
            .filter(
                CaseInputAssignment.case_id == case_id,
                CaseInputAssignment.ended_at.is_(None),
            )
            .first()
        )

    def add_case_input_assignment(self, row: CaseInputAssignment):
        self.session.add(row)
        return row

    def existing_assignment_counts(self, project_id):
        input_counts = Counter()
        reviewer_counts = Counter()
        rows = (
            self.session.query(
                ProjectCase.assigned_input_user_id,
                ProjectCase.assigned_reviewer_user_id,
            )
            .filter(ProjectCase.project_id == project_id)
            .all()
        )
        for input_user_id, reviewer_user_id in rows:
            if input_user_id is not None:
                input_counts[input_user_id] += 1
            if reviewer_user_id is not None:
                reviewer_counts[reviewer_user_id] += 1
        return input_counts, reviewer_counts

    def active_pdf_counts_by_case(self, project_id):
        rows = (
            self.session.query(
                ProjectDocumentAsset.case_id,
                func.count(ProjectDocumentAsset.id),
            )
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.status == "active",
            )
            .group_by(ProjectDocumentAsset.case_id)
            .all()
        )
        return {
            case_id: int(pdf_count or 0)
            for case_id, pdf_count in rows
        }

    def add_history(
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
        self.session.add(
            ProjectAssignmentHistory(
                project_id=project_id,
                case_id=case_id,
                assignment_role=assignment_role,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                changed_by_user_id=changed_by_user_id,
                reason=reason,
            )
        )

    def data_entry_completion_by_case(self, case_ids: list[int]) -> dict[int, bool]:
        if not case_ids:
            return {}
        report_counts = dict(
            self.session.query(ProjectReportUnit.case_id, func.count(ProjectReportUnit.id))
            .filter(ProjectReportUnit.case_id.in_(case_ids))
            .group_by(ProjectReportUnit.case_id)
            .all()
        )
        entered_counts = dict(
            self.session.query(
                ProjectDocumentAsset.case_id,
                func.count(func.distinct(ProjectDocumentAsset.report_unit_id)),
            )
            .join(
                Submission,
                Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id,
            )
            .filter(
                ProjectDocumentAsset.case_id.in_(case_ids),
                Submission.status.in_(NON_DRAFT_STATUSES),
            )
            .group_by(ProjectDocumentAsset.case_id)
            .all()
        )
        return {
            cid: (report_counts.get(cid, 0) > 0 and entered_counts.get(cid, 0) >= report_counts.get(cid, 0))
            for cid in case_ids
        }

    def list_action_needed_cases(self, project_id: int | None = None) -> list[dict]:
        query = (
            self.session.query(
                ProjectCase,
                Project,
                User,
                CaseInputAssignment,
            )
            .join(Project, Project.id == ProjectCase.project_id)
            .join(User, User.id == ProjectCase.assigned_input_user_id)
            .outerjoin(
                CaseInputAssignment,
                (CaseInputAssignment.case_id == ProjectCase.id)
                & (CaseInputAssignment.ended_at.is_(None)),
            )
            .filter(ProjectCase.assigned_input_user_id.is_not(None))
        )
        if project_id is not None:
            query = query.filter(ProjectCase.project_id == project_id)

        rows = query.order_by(Project.name, ProjectCase.case_key, ProjectCase.id).all()
        if not rows:
            return []

        now = get_utc_now()
        overdue_candidate_ids = [
            case_row.id
            for case_row, _, _, assignment in rows
            if assignment is not None and assignment.due_at is not None and assignment.due_at < now
        ]
        completion_status = self.data_entry_completion_by_case(overdue_candidate_ids)

        action_needed = []
        for case_row, project_row, user_row, assignment in rows:
            issues = []
            if account_policy.is_locked(user_row):
                issues.append("user_locked")
            if account_policy.is_expired(user_row):
                issues.append("ctv_expired")

            is_overdue = False
            if assignment is not None and assignment.due_at is not None and assignment.due_at < now:
                if not completion_status.get(case_row.id, False):
                    issues.append("overdue")
                    is_overdue = True

            if issues:
                action_needed.append({
                    "project_id": project_row.id,
                    "project_name": project_row.name,
                    "case_id": case_row.id,
                    "case_key": case_row.case_key,
                    "display_name": case_row.display_name,
                    "assigned_user_id": user_row.id,
                    "assigned_username": user_row.username,
                    "assigned_full_name": user_row.full_name or user_row.username,
                    "account_type": user_row.account_type,
                    "account_role": user_row.role,
                    "is_locked": bool(user_row.is_locked),
                    "expires_on": user_row.expires_on.isoformat() if user_row.expires_on else None,
                    "assigned_at": (
                        assignment.assigned_at.replace(tzinfo=timezone.utc).isoformat()
                        if assignment and assignment.assigned_at
                        else None
                    ),
                    "due_at": (
                        assignment.due_at.replace(tzinfo=timezone.utc).isoformat()
                        if assignment and assignment.due_at
                        else None
                    ),
                    "deadline_days": assignment.deadline_days if assignment else None,
                    "issues": issues,
                    "is_overdue": is_overdue,
                    "assigned_reviewer_user_id": case_row.assigned_reviewer_user_id,
                })
        return action_needed

    def list_ready_input_cases(self, project_id: int, previous_stage_key: str | None) -> list[dict]:
        cases = (
            self.session.query(ProjectCase)
            .filter(
                ProjectCase.project_id == project_id,
                ProjectCase.assigned_input_user_id.is_(None),
            )
            .order_by(ProjectCase.case_key, ProjectCase.id)
            .all()
        )
        if not cases:
            return []

        cases = [c for c in cases if not is_placeholder_box_key(c.case_key)]
        if not cases:
            return []

        pdf_counts = self.active_pdf_counts_by_case(project_id)
        cases = [c for c in cases if pdf_counts.get(c.id, 0) > 0]
        if not cases:
            return []

        if previous_stage_key is None:
            ready_cases = cases
        else:
            case_ids = [c.id for c in cases]
            done_case_ids = {
                row[0]
                for row in self.session.query(CaseStageState.case_id)
                .filter(
                    CaseStageState.case_id.in_(case_ids),
                    CaseStageState.stage_key == previous_stage_key,
                    CaseStageState.status == "done",
                )
                .all()
            }
            ready_cases = [c for c in cases if c.id in done_case_ids]

        return [
            {
                "case_id": c.id,
                "case_key": c.case_key,
                "display_name": c.display_name,
                "pdf_count": pdf_counts.get(c.id, 0),
                "assigned_reviewer_user_id": c.assigned_reviewer_user_id,
            }
            for c in ready_cases
        ]
