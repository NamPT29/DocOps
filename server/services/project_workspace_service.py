import json
from urllib.parse import quote

from fastapi import HTTPException

from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
)
from server.repositories.project_workspace_repository import ProjectWorkspaceRepository


def _project_folder_group(project_id, case_key):
    normalized_case_key = str(case_key or "__ROOT__").replace("\\", "/").strip("/")
    return f"project/{project_id}/{normalized_case_key or '__ROOT__'}"


def _document_workflow_status(asset_status, submission_statuses):
    if asset_status != "active":
        return asset_status
    return "completed" if submission_statuses else "pending"


def sync_project_assets_to_documents(db, *, project_id):
    repository = ProjectWorkspaceRepository(db)
    project = repository.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    rows = repository.list_assets_with_cases(project_id)
    linked_document_ids = {
        asset.assigned_document_id
        for asset, _case_row in rows
        if asset.assigned_document_id is not None
    }
    statuses_by_document = repository.submission_statuses_by_document(linked_document_ids)
    created = 0
    updated = 0

    for asset, case_row in rows:
        document = (
            repository.get_document(asset.assigned_document_id)
            if asset.assigned_document_id is not None
            else None
        )
        if asset.assigned_document_id is not None and document is None:
            asset.assigned_document_id = None

        if document is None and asset.status == "active":
            document = repository.add_document(
                AssignedDocument(
                    original_filename=asset.original_filename,
                    uuid_filename=asset.storage_filename,
                    assigned_to_user_id=case_row.assigned_input_user_id,
                    template_id=project.template_id,
                    status="pending",
                )
            )
            db.flush()
            asset.assigned_document_id = document.id
            statuses_by_document[document.id] = []
            created += 1

        if document is None:
            continue

        document.original_filename = asset.original_filename
        document.uuid_filename = asset.storage_filename
        document.assigned_to_user_id = case_row.assigned_input_user_id
        document.template_id = project.template_id
        document.status = _document_workflow_status(
            asset.status,
            statuses_by_document.get(document.id, []),
        )

        path = repository.get_document_path(document.id)
        if path:
            path.relative_path = asset.relative_path
        else:
            repository.add_document_path(
                AssignedDocumentPath(
                    document_id=document.id,
                    relative_path=asset.relative_path,
                    upload_id=f"project-asset-{asset.id}",
                )
            )

        folder_group = _project_folder_group(project.id, case_row.case_key)
        folder = repository.get_document_folder(document.id)
        if folder:
            folder.folder_group = folder_group
        else:
            repository.add_document_folder(
                AssignedDocumentFolder(
                    document_id=document.id,
                    folder_group=folder_group,
                )
            )

        review_assignment = repository.get_document_review_assignment(document.id)
        reviewer_user_id = case_row.assigned_reviewer_user_id
        if reviewer_user_id is None:
            if review_assignment:
                repository.delete_document_review_assignment(review_assignment)
        elif review_assignment:
            review_assignment.reviewer_user_id = reviewer_user_id
        else:
            repository.add_document_review_assignment(
                AssignedDocumentReviewAssignment(
                    document_id=document.id,
                    reviewer_user_id=reviewer_user_id,
                )
            )
        updated += 1

    db.flush()
    return {"created_documents": created, "updated_documents": updated}


def get_project_workspace(db, *, project_id, current_user):
    repository = ProjectWorkspaceRepository(db)
    project = repository.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    if (
        current_user.get("role") != "admin"
        and not repository.user_is_active_member(project_id, current_user["id"])
    ):
        raise HTTPException(status_code=403, detail="Bạn không thuộc dự án này")

    try:
        schema = json.loads(project.form_schema_json_snapshot or "[]")
    except (TypeError, ValueError):
        schema = []
    try:
        config = json.loads(project.template_config_json_snapshot or "{}")
    except (TypeError, ValueError):
        config = {}

    rows = repository.list_input_workspace_assets(project.id, current_user["id"])
    files = []
    for asset, case_row, report, document in rows:
        files.append({
            "name": asset.original_filename,
            "url": f"/api/files/{quote(asset.storage_filename, safe='')}",
            "uuid": asset.storage_filename,
            "relative_path": asset.relative_path,
            "folder_group": _project_folder_group(project.id, case_row.case_key),
            "case_id": case_row.id,
            "case_name": case_row.display_name,
            "report_unit_id": report.id,
            "report_name": report.display_name,
            "template_id": project.template_id,
            "template_name": project.template_name_snapshot,
            "entered": bool(document and document.status == "completed"),
        })

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "template_id": project.template_id,
            "template_name": project.template_name_snapshot,
        },
        "schema": schema,
        "config": config,
        "files": files,
    }
