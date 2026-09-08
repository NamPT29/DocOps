from server.models import AssignedDocument, Submission


from server.utils.folder_utils import (
    folder_path_key,
    normalize_folder_path,
)


def apply_submission_metadata(
    submission: Submission,
    data: dict,
    *,
    document: AssignedDocument | None = None,
    folder_path: object = None,
) -> None:
    normalized_folder = normalize_folder_path(
        folder_path if folder_path is not None else data.get("_folder_path")
    )
    submission.assigned_document_id = getattr(document, "id", None)
    submission.folder_path = normalized_folder or None
    submission.folder_path_key = folder_path_key(normalized_folder)
