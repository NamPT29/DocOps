from server.repositories.personnel_statistics_repository import (
    PersonnelStatisticsRepository,
)


def get_personnel_statistics(db):
    repository = PersonnelStatisticsRepository(db)
    active_projects = repository.active_project_counts()
    submitted_reports = repository.submitted_report_counts()
    reviewed_reports = repository.first_reviewed_report_counts()
    input_error_reports = repository.input_error_report_counts()
    reviewer_error_fields = repository.reviewer_error_field_counts()

    return [
        {
            "user_id": user.id,
            "username": user.username,
            "full_name": str(user.full_name or "").strip() or user.username,
            "active_project_count": active_projects.get(user.id, 0),
            "submitted_report_count": submitted_reports.get(user.id, 0),
            "reviewed_report_count": reviewed_reports.get(user.id, 0),
            "input_error_report_count": input_error_reports.get(user.id, 0),
            "reviewer_error_field_count": reviewer_error_fields.get(user.id, 0),
        }
        for user in repository.list_personnel()
    ]
