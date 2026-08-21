from server.repositories.project_assignment_repository import ProjectAssignmentRepository


def _least_loaded_user(eligible_user_ids, counts):
    if not eligible_user_ids:
        return None
    return min(eligible_user_ids, key=lambda user_id: (counts[user_id], user_id))


def assign_unassigned_project_cases(db, *, project_id, changed_by_user_id):
    repository = ProjectAssignmentRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        return {"input_assigned": 0, "reviewer_assigned": 0}

    input_user_ids = repository.active_member_ids(project_id, "input")
    reviewer_user_ids = repository.active_member_ids(project_id, "reviewer")
    cases = repository.lock_cases(project_id)
    input_counts, reviewer_counts = repository.existing_assignment_counts(project_id)
    input_assigned = 0
    reviewer_assigned = 0

    for case_row in cases:
        if case_row.assigned_input_user_id is None:
            input_user_id = _least_loaded_user(input_user_ids, input_counts)
            if input_user_id is not None:
                case_row.assigned_input_user_id = input_user_id
                input_counts[input_user_id] += 1
                input_assigned += 1
                repository.add_history(
                    project_id=project_id,
                    case_id=case_row.id,
                    assignment_role="input",
                    from_user_id=None,
                    to_user_id=input_user_id,
                    changed_by_user_id=changed_by_user_id,
                    reason="initial_import",
                )

        if case_row.assigned_reviewer_user_id == case_row.assigned_input_user_id:
            previous_reviewer_id = case_row.assigned_reviewer_user_id
            if previous_reviewer_id is not None:
                reviewer_counts[previous_reviewer_id] -= 1
            case_row.assigned_reviewer_user_id = None
            repository.add_history(
                project_id=project_id,
                case_id=case_row.id,
                assignment_role="reviewer",
                from_user_id=previous_reviewer_id,
                to_user_id=None,
                changed_by_user_id=changed_by_user_id,
                reason="prevent_self_review",
            )

        if case_row.assigned_reviewer_user_id is None:
            eligible_reviewers = [
                user_id
                for user_id in reviewer_user_ids
                if user_id != case_row.assigned_input_user_id
            ]
            reviewer_user_id = _least_loaded_user(eligible_reviewers, reviewer_counts)
            if reviewer_user_id is not None:
                case_row.assigned_reviewer_user_id = reviewer_user_id
                reviewer_counts[reviewer_user_id] += 1
                reviewer_assigned += 1
                repository.add_history(
                    project_id=project_id,
                    case_id=case_row.id,
                    assignment_role="reviewer",
                    from_user_id=None,
                    to_user_id=reviewer_user_id,
                    changed_by_user_id=changed_by_user_id,
                    reason="initial_import",
                )

    db.flush()
    return {
        "input_assigned": input_assigned,
        "reviewer_assigned": reviewer_assigned,
    }
