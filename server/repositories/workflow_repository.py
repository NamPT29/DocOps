from sqlalchemy import func

from server.models import (
    ArrangementDossier,
    CaseStageEvent,
    CaseStageState,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    ProjectStage,
    ProjectStageMember,
    Submission,
    User,
)
from server.models_scan import CaseScanPackage

UNDER_REVIEW_STATUSES = ("pending_review", "pending_input_confirmation")


class WorkflowRepository:
    def __init__(self, session):
        self.session = session

    # -- project / configuration -------------------------------------------------
    def get_project(self, project_id):
        return self.session.get(Project, project_id)

    def catalog_dossier_count(self, case_id):
        """Arrangement catalogue rows of one box (FR-ARR-01)."""
        return self.session.query(func.count(ArrangementDossier.id)).filter(
            ArrangementDossier.case_id == case_id
        ).scalar() or 0

    def get_latest_scan_package(self, case_id):
        """Returns the latest scan package for the given case."""
        return (
            self.session.query(CaseScanPackage)
            .filter(CaseScanPackage.case_id == case_id)
            .order_by(CaseScanPackage.version.desc())
            .first()
        )

    def get_scan_packages(self, case_id):
        """Returns all scan packages for the given case."""
        return (
            self.session.query(CaseScanPackage)
            .filter(CaseScanPackage.case_id == case_id)
            .order_by(CaseScanPackage.version.desc())
            .all()
        )

    def stage_rows(self, project_id):
        return (
            self.session.query(ProjectStage)
            .filter(ProjectStage.project_id == project_id)
            .order_by(ProjectStage.position)
            .all()
        )

    def add_stage(self, row):
        self.session.add(row)
        return row

    def stage_member_rows(self, project_id):
        return (
            self.session.query(ProjectStageMember)
            .filter(ProjectStageMember.project_id == project_id)
            .all()
        )

    def add_stage_member(self, row):
        self.session.add(row)
        return row

    def users_by_ids(self, user_ids):
        if not user_ids:
            return {}
        return {
            user.id: user
            for user in self.session.query(User).filter(User.id.in_(set(user_ids))).all()
        }

    def legacy_member_ids(self, project_id, member_role):
        rows = (
            self.session.query(ProjectMember.user_id)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.member_role == member_role,
                ProjectMember.is_active.is_(True),
            )
            .order_by(ProjectMember.user_id)
            .all()
        )
        return [row[0] for row in rows]

    def user_is_stage_member(self, project_id, user_id, stage_key):
        return (
            self.session.query(ProjectStageMember.user_id)
            .filter(
                ProjectStageMember.project_id == project_id,
                ProjectStageMember.user_id == user_id,
                ProjectStageMember.stage_key == stage_key,
                ProjectStageMember.is_active.is_(True),
            )
            .first()
            is not None
        )

    def user_is_stage_member_in_any_project(self, user_id, stage_key):
        return (
            self.session.query(ProjectStageMember.user_id)
            .filter(
                ProjectStageMember.user_id == user_id,
                ProjectStageMember.stage_key == stage_key,
                ProjectStageMember.is_active.is_(True),
            )
            .first()
            is not None
        )

    def user_has_legacy_role(self, project_id, user_id, member_role):
        return (
            self.session.query(ProjectMember.user_id)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.member_role == member_role,
                ProjectMember.is_active.is_(True),
            )
            .first()
            is not None
        )

    # -- cases / states ------------------------------------------------------------
    def get_case(self, project_id, case_id):
        return (
            self.session.query(ProjectCase)
            .filter(ProjectCase.project_id == project_id, ProjectCase.id == case_id)
            .first()
        )

    def count_cases(self, project_id):
        return (
            self.session.query(func.count(ProjectCase.id))
            .filter(ProjectCase.project_id == project_id)
            .scalar()
            or 0
        )

    def list_cases(self, project_id, *, offset=None, limit=None):
        query = (
            self.session.query(ProjectCase)
            .filter(ProjectCase.project_id == project_id)
            .order_by(ProjectCase.case_key, ProjectCase.id)
        )
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()

    def case_ids_with_active_pdfs(self, project_id):
        rows = (
            self.session.query(ProjectDocumentAsset.case_id)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.status == "active",
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    def states_for_project(self, project_id):
        return (
            self.session.query(CaseStageState)
            .filter(CaseStageState.project_id == project_id)
            .all()
        )

    def get_state(self, case_id, stage_key, *, lock=False):
        query = self.session.query(CaseStageState).filter(
            CaseStageState.case_id == case_id,
            CaseStageState.stage_key == stage_key,
        )
        if lock:
            query = query.with_for_update()
        return query.first()

    def states_for_case(self, case_id):
        return (
            self.session.query(CaseStageState)
            .filter(CaseStageState.case_id == case_id)
            .all()
        )

    def add_state(self, row):
        self.session.add(row)
        return row

    def add_event(self, row):
        self.session.add(row)
        return row

    def events_for_case(self, case_id, *, limit=200):
        return (
            self.session.query(CaseStageEvent)
            .filter(CaseStageEvent.case_id == case_id)
            .order_by(CaseStageEvent.id.desc())
            .limit(limit)
            .all()
        )

    def flush(self):
        self.session.flush()

    # -- derived data-entry progress ---------------------------------------------
    def entry_progress_by_case(self, project_id, case_id=None):
        """Per-case submission counts used to derive data_entry / entry_qc."""
        progress = {}
        report_query = (
            self.session.query(ProjectReportUnit.case_id, func.count(ProjectReportUnit.id))
            .filter(ProjectReportUnit.project_id == project_id)
        )
        if case_id is not None:
            report_query = report_query.filter(ProjectReportUnit.case_id == case_id)
        report_rows = report_query.group_by(ProjectReportUnit.case_id).all()
        for row_case_id, report_total in report_rows:
            progress[row_case_id] = {
                "report_total": int(report_total or 0),
                "reports_entered": 0,
                "submissions_total": 0,
                "submissions_under_review": 0,
                "submissions_completed": 0,
            }

        submission_query = (
            self.session.query(
                ProjectDocumentAsset.case_id,
                ProjectDocumentAsset.report_unit_id,
                Submission.status,
                func.count(Submission.id),
            )
            .join(
                Submission,
                Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id,
            )
            .filter(ProjectDocumentAsset.project_id == project_id)
        )
        if case_id is not None:
            submission_query = submission_query.filter(ProjectDocumentAsset.case_id == case_id)
        rows = (
            submission_query
            .group_by(
                ProjectDocumentAsset.case_id,
                ProjectDocumentAsset.report_unit_id,
                Submission.status,
            )
            .all()
        )
        entered_reports = {}
        for row_case_id, report_unit_id, status, count in rows:
            entry = progress.setdefault(row_case_id, {
                "report_total": 0,
                "reports_entered": 0,
                "submissions_total": 0,
                "submissions_under_review": 0,
                "submissions_completed": 0,
            })
            count = int(count or 0)
            entry["submissions_total"] += count
            if status == "completed":
                entry["submissions_completed"] += count
            elif status in UNDER_REVIEW_STATUSES:
                entry["submissions_under_review"] += count
            entered_reports.setdefault(row_case_id, set()).add(report_unit_id)
        for row_case_id, units in entered_reports.items():
            progress[row_case_id]["reports_entered"] = len(units)
        return progress

    def get_my_projects_data(self, user_id):
        # 1. Get enabled stages per project
        stage_rows = self.session.query(ProjectStage.project_id, ProjectStage.stage_key, ProjectStage.position).filter(
            ProjectStage.is_enabled.is_(True)
        ).all()
        
        # 2. Get user's stage memberships
        member_rows = self.session.query(ProjectStageMember.project_id, ProjectStageMember.stage_key).filter(
            ProjectStageMember.user_id == user_id,
            ProjectStageMember.is_active.is_(True)
        ).all()
        
        # 3. Get user's reviewer memberships
        reviewer_rows = self.session.query(ProjectMember.project_id).filter(
            ProjectMember.user_id == user_id,
            ProjectMember.member_role == "reviewer",
            ProjectMember.is_active.is_(True)
        ).all()
        
        # 4. Get project names
        project_ids = set([r[0] for r in member_rows] + [r[0] for r in reviewer_rows])
        if not project_ids:
            return []
        projects = self.session.query(Project.id, Project.name).filter(Project.id.in_(project_ids)).all()
        project_names = {p[0]: p[1] for p in projects}
        
        # Aggregate
        enabled_stages_by_project = {}
        for pid, stage_key, position in stage_rows:
            enabled_stages_by_project.setdefault(pid, []).append((position, stage_key))
            
        for pid in enabled_stages_by_project:
            enabled_stages_by_project[pid].sort()

        allowed_stages_by_project = {}
        for pid, stage_key in member_rows:
            allowed_stages_by_project.setdefault(pid, set()).add(stage_key)
            
        reviewer_pids = {r[0] for r in reviewer_rows}
        
        result = []
        for pid in project_ids:
            if pid not in project_names:
                continue
            # Only include enabled stages that the user is a member of
            enabled = [s[1] for s in enabled_stages_by_project.get(pid, [])]
            allowed = allowed_stages_by_project.get(pid, set())
            user_stages = [k for k in enabled if k in allowed]
            is_reviewer = pid in reviewer_pids
            
            # Project is only included if they have some access
            if user_stages or is_reviewer:
                result.append({
                    "project_id": pid,
                    "name": project_names[pid],
                    "stages": user_stages,
                    "is_reviewer": is_reviewer
                })
                
        # Sort by project_id descending (newest first)
        result.sort(key=lambda x: x["project_id"], reverse=True)
        return result

