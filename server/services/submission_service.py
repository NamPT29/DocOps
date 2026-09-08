from server.services.submission_helpers import COMPLETED_WITHOUT_FOLDER, _pdf_url
from server.services.submission_metadata_service import apply_submission_metadata
from server.services.submission_quality_service import SubmissionQualityService
from server.repositories.submission_quality_repository import SubmissionQualityRepository
from server.repositories.submission_review_history_repository import (
    SubmissionReviewHistoryRepository,
)

from typing import Literal
from fastapi import HTTPException
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from server.models import AssignedDocument, Submission, Template
from server.repositories import (
    DocumentRepository,
    LookupRepository,
    ReviewRepository,
    SubmissionRepository,
    SubmissionViewRepository,
    TemplateRepository,
)
from server.utils.folder_utils import (
    NO_FOLDER_SENTINEL,
    normalize_folder_path,
)

def _load_submission_document_metadata(
    submissions: list[Submission],
    db: Session,
) -> dict[int, dict]:
    document_ids = {
        submission.assigned_document_id
        for submission in submissions
        if submission.assigned_document_id is not None
    }
    metadata = DocumentRepository(db).metadata_map(document_ids)
    for item in metadata.values():
        item["folder_path"] = normalize_folder_path(item["folder_path"])
    return metadata


_CONTEXT_UNSET = object()

class SubmissionService:

    @staticmethod
    def sync_cover_data(
        submission: Submission,
        template_id: int,
        data_dict: dict,
        db: Session,
    ) -> None:
        if not template_id:
            return
            
        from server.repositories import TemplateRepository, SubmissionRepository
        template = TemplateRepository(db).get(template_id)
        if not template or not template.config_json:
            return
            
        config = json.loads(template.config_json)
        cover_cols = config.get("cover_cols", [])
        cover_folder_level = config.get("cover_folder_level", 0)
        
        if not cover_cols or cover_folder_level <= 0:
            return
            
        folder_path = submission.folder_path
        if not folder_path or folder_path == NO_FOLDER_SENTINEL:
            return
            
        # Tính toán target_folder_path dựa trên cover_folder_level
        # Ví dụ: folder_path = "A/B/C/D", cover_folder_level = 1 -> target = "A/B/C/D"
        # cover_folder_level = 2 -> target = "A/B/C"
        parts = folder_path.split("/")
        if len(parts) >= cover_folder_level:
            target_parts = parts[:len(parts) - cover_folder_level + 1]
        else:
            target_parts = parts
            
        # Lấy tất cả submission cùng template
        all_subs = SubmissionRepository(db).list_by_template_id(template_id)
        
        updates_count = 0
        for sub in all_subs:
            if sub.id == submission.id:
                continue
            if not sub.folder_path or sub.folder_path == NO_FOLDER_SENTINEL:
                continue
            
            sub_parts = sub.folder_path.split("/")
            if len(sub_parts) >= len(target_parts) and sub_parts[:len(target_parts)] == target_parts:
                sub_data = json.loads(sub.data_json) if sub.data_json else {}
                changed = False
                for c in cover_cols:
                    key = f"col_{c-1}"
                    if sub_data.get(key) != data_dict.get(key):
                        sub_data[key] = data_dict.get(key, "")
                        changed = True
                if changed:
                    sub.data_json = json.dumps(sub_data, ensure_ascii=False)
                    updates_count += 1


    @staticmethod
    def sync_submission_metadata(
        submission: Submission,
        data: dict,
        document: AssignedDocument | None,
        db: Session,
        *,
        document_folder_path: object = _CONTEXT_UNSET,
    ) -> None:
        folder_path = normalize_folder_path(data.get("_folder_path"))
        if not folder_path and document:
            if document_folder_path is _CONTEXT_UNSET:
                folder_metadata = DocumentRepository(db).get_folder(document.id)
                document_folder_path = getattr(folder_metadata, "folder_group", None)
            folder_path = normalize_folder_path(document_folder_path)
        apply_submission_metadata(
            submission,
            data,
            document=document,
            folder_path=folder_path,
        )


    @staticmethod
    def bulk_submission_action(
        db: Session,
        action: Literal["delete", "submit_for_review"],
        submission_ids: list[int],
        current_user: dict
    ) -> int:
        submission_repository = SubmissionRepository(db)
        selected = submission_repository.list_by_ids(submission_ids)
        if len(selected) != len(submission_ids):
            raise HTTPException(status_code=404, detail="Có hồ sơ không tồn tại")
        if current_user["role"] != "admin":
            active_input_user_ids = submission_repository.active_input_user_ids(selected)
            if any(
                active_input_user_ids.get(submission.id) != current_user["id"]
                for submission in selected
            ):
                raise HTTPException(status_code=403, detail="Bạn không có quyền xử lý một hoặc nhiều hồ sơ đã chọn")

        view_repository = SubmissionViewRepository(db)
        active_viewers = view_repository.active_map(submission_ids)
        conflict = next(
            (
                viewer
                for viewer in active_viewers.values()
                if viewer.get("user_id") != current_user["id"]
            ),
            None,
        )
        if conflict:
            viewer_name = conflict.get("username") or "Người dùng khác"
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "submission_view_conflict",
                    "message": f"{viewer_name} đang mở một hồ sơ đã chọn. Vui lòng thử lại sau.",
                    "viewing_user_id": conflict.get("user_id"),
                    "viewing_user_name": viewer_name,
                },
            )
        # A bulk action intentionally supersedes this user's own open tabs.
        # Releasing in the same transaction also prevents stale presences from
        # blocking the newly assigned reviewer after a bulk submit.
        view_repository.release_owned(submission_ids, current_user["id"])

        if action == "delete":
            invalid = [submission.id for submission in selected if submission.status != "draft"]
            if invalid:
                raise HTTPException(
                    status_code=409,
                    detail="Chỉ có thể xóa hàng loạt các hồ sơ đang lưu nháp",
                )
            doc_ids = {s.assigned_document_id for s in selected if s.assigned_document_id}
            ReviewRepository(db).delete_for_submissions(submission_ids)
            for submission in selected:
                submission_repository.delete(submission)
            db.flush()

            if doc_ids:
                doc_repo = DocumentRepository(db)
                submission_counts = submission_repository.counts_by_document_ids(doc_ids)
                documents = doc_repo.map_by_ids(doc_ids)
                for doc_id in doc_ids:
                    other_count = submission_counts.get(doc_id, 0)
                    if other_count == 0:
                        document = documents.get(doc_id)
                        if document and document.status == "completed":
                            document.status = "pending"
        else:
            invalid = [
                submission.id
                for submission in selected
                if submission.status != "draft"
            ]
            if invalid:
                raise HTTPException(
                    status_code=409,
                    detail="Chỉ hồ sơ lưu nháp mới có thể nộp duyệt",
                )

            parsed_data: dict[int, dict] = {}
            for submission in selected:
                try:
                    raw_data = json.loads(submission.data_json or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Hồ sơ {submission.id} chứa dữ liệu không hợp lệ",
                    )
                if not isinstance(raw_data, dict):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Hồ sơ {submission.id} chứa dữ liệu không hợp lệ",
                    )
                parsed_data[submission.id] = raw_data

            template_ids = {
                submission.template_id
                for submission in selected
                if submission.template_id is not None
            }
            templates = TemplateRepository(db).map_by_ids(template_ids)
            template_configs = {
                template_id: SubmissionService._template_config(template)
                for template_id, template in templates.items()
            }
            for submission in selected:
                SubmissionService.validate_required_fields(
                    submission.template_id,
                    parsed_data[submission.id],
                    db,
                    allow_missing_linked_path=True,
                    template_config=template_configs.get(submission.template_id, {}),
                )

            document_repository = DocumentRepository(db)
            documents = document_repository.map_by_ids({
                submission.assigned_document_id
                for submission in selected
                if submission.assigned_document_id is not None
            })
            resolved_documents = {
                submission.id: documents.get(submission.assigned_document_id)
                for submission in selected
            }
            document_metadata = document_repository.metadata_map({
                document.id
                for document in resolved_documents.values()
                if document is not None
            })

            prepared_data: dict[int, dict] = {}
            for submission in selected:
                document = resolved_documents[submission.id]
                metadata = document_metadata.get(document.id) if document else None
                data_dict = SubmissionService._enrich_pdf_reference_from_context(
                    parsed_data[submission.id],
                    document,
                    metadata,
                )
                prepared_data[submission.id] = data_dict
                SubmissionService.sync_submission_metadata(
                    submission,
                    data_dict,
                    document,
                    db,
                    document_folder_path=(
                        metadata.get("folder_path") if metadata else None
                    ),
                )

            for template_id in template_ids:
                SubmissionService.lock_duplicate_scope(template_id, db)
            duplicate_candidates = submission_repository.exact_duplicate_candidates_by_scope(
                {
                    (submission.template_id, submission.folder_path_key)
                    for submission in selected
                },
                exclude_submission_ids={submission.id for submission in selected},
            )
            for submission in selected:
                duplicate_count = SubmissionService.exact_duplicate_count(
                    submission,
                    prepared_data[submission.id],
                    db,
                    template_config=template_configs.get(submission.template_id, {}),
                    candidates=duplicate_candidates.get(
                        (submission.template_id, submission.folder_path_key),
                        [],
                    ),
                )
                if duplicate_count:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "duplicate_submission",
                            "duplicate_count": duplicate_count,
                            "message": (
                                f"Hồ sơ {submission.id} trùng path và nội dung với "
                                f"{duplicate_count} báo cáo khác. Toàn bộ lô vẫn được giữ nguyên."
                            ),
                        },
                    )

            from server.services.review_workflow_service import ReviewWorkflowService
            ReviewWorkflowService.assign_submission_reviewers(
                selected,
                db,
                required=False,
            )
            quality_repository = SubmissionQualityRepository(db)
            quality_repository.prime_for_submissions(
                [submission.id for submission in selected]
            )
            quality_repository.prime_projects_for_documents({
                submission.assigned_document_id
                for submission in selected
                if submission.assigned_document_id is not None
            })

            submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            for submission in selected:
                data_dict = prepared_data[submission.id]
                document = resolved_documents[submission.id]
                data_dict.pop("_wrong_sections", None)
                data_dict.pop("_wrong_fields", None)
                SubmissionQualityService.ensure_baseline(
                    submission,
                    data_dict,
                    db,
                )
                submission.data_json = json.dumps(data_dict, ensure_ascii=False)
                submission.status = "pending_review"
                submission.created_at = submitted_at
                if document:
                    document.status = "completed"

        db.commit()
        return len(selected)

    @staticmethod
    def folder_files_for_document(document: AssignedDocument | None, db: Session) -> list[dict]:
        if not document:
            return []
        repository = DocumentRepository(db)
        folder = repository.get_folder(document.id)
        if not folder or not folder.folder_group:
            return []
        rows = repository.list_folder_files(folder.folder_group)
        return [
            {
                "name": item.original_filename,
                "uuid": item.uuid_filename,
                "url": _pdf_url(item.uuid_filename),
                "relative_path": relative_path,
                "folder_group": folder.folder_group,
                "template_id": item.template_id,
                "submission_id": submission_id,
                "review_status": submission_status,
            }
            for item, relative_path, submission_id, submission_status in rows
        ]

    @staticmethod
    def resolve_document(data: dict, db: Session, owner_id: int, pending_only: bool = False) -> AssignedDocument | None:
        uuid_filename = data.get("_pdf_uuid")
        original_filename = data.get("_pdf_filename")
        if not uuid_filename and not original_filename:
            return None

        return DocumentRepository(db).resolve_reference(
            owner_id=owner_id,
            uuid_filename=uuid_filename,
            original_filename=original_filename,
            pending_only=pending_only,
        )

    @staticmethod
    def enrich_pdf_reference(
        data: dict,
        db: Session,
        owner_id: int,
        pending_only: bool = False,
    ):
        enriched = dict(data)
        document = SubmissionService.resolve_document(enriched, db, owner_id, pending_only)
        if document:
            enriched["_pdf_filename"] = document.original_filename
            enriched["_pdf_uuid"] = document.uuid_filename
            enriched["_pdf_url"] = _pdf_url(document.uuid_filename)
            relative_path, folder_group = DocumentRepository(db).get_path_and_folder(
                document.id
            )
            if relative_path:
                enriched["_pdf_relative_path"] = relative_path
            else:
                enriched.pop("_pdf_relative_path", None)
            if folder_group and folder_group != "__ROOT__":
                enriched["_folder_path"] = folder_group
            else:
                enriched.pop("_folder_path", None)
        elif enriched.get("_pdf_uuid"):
            raise HTTPException(status_code=400, detail="File đính kèm không thuộc người dùng")
        elif enriched.get("_pdf_filename"):
            raise HTTPException(status_code=400, detail="Không xác minh được file đính kèm")
        return enriched, document

    @staticmethod
    def _enrich_pdf_reference_from_context(
        data: dict,
        document: AssignedDocument | None,
        metadata: dict | None,
    ) -> dict:
        """Query-free enrichment from authoritative document metadata."""
        enriched = dict(data)
        if document:
            enriched["_pdf_filename"] = document.original_filename
            enriched["_pdf_uuid"] = document.uuid_filename
            enriched["_pdf_url"] = _pdf_url(document.uuid_filename)
            relative_path = (metadata or {}).get("relative_path")
            folder_group = (metadata or {}).get("folder_path")
            if relative_path:
                enriched["_pdf_relative_path"] = relative_path
            else:
                enriched.pop("_pdf_relative_path", None)
            if folder_group and folder_group != "__ROOT__":
                enriched["_folder_path"] = folder_group
            else:
                enriched.pop("_folder_path", None)
        elif enriched.get("_pdf_uuid"):
            raise HTTPException(status_code=400, detail="File đính kèm không thuộc người dùng")
        elif enriched.get("_pdf_filename"):
            raise HTTPException(status_code=400, detail="Không xác minh được file đính kèm")
        return enriched

    @staticmethod
    def _template_config(template: Template | None) -> dict:
        if not template or not template.config_json:
            return {}
        try:
            config = json.loads(template.config_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return config if isinstance(config, dict) else {}

    @staticmethod
    def _copy_linked_path_field(template_id: int | None, db: Session) -> str | None:
        if not template_id:
            return None
        template = TemplateRepository(db).get(template_id)
        if not template or not template.config_json:
            return None
        try:
            config = json.loads(template.config_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        linked_path_config = config.get("linked_pdf_path") or {}
        if linked_path_config.get("enabled") is not True:
            return None
        try:
            linked_path_col = int(linked_path_config.get("col"))
        except (TypeError, ValueError):
            return None
        return f"col_{linked_path_col - 1}" if linked_path_col > 0 else None

    @staticmethod
    def _normalize_copy_value(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [SubmissionService._normalize_copy_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: SubmissionService._normalize_copy_value(value[key])
                for key in sorted(value)
            }
        return value

    @staticmethod
    def _copy_business_changed(
        source_data: dict,
        target_data: dict,
        ignored_path_field: str | None,
    ) -> bool:
        keys = {
            key
            for key in set(source_data) | set(target_data)
            if isinstance(key, str)
            and not key.startswith("_")
            and key != ignored_path_field
        }
        return any(
            SubmissionService._normalize_copy_value(source_data.get(key))
            != SubmissionService._normalize_copy_value(target_data.get(key))
            for key in keys
        )

    @staticmethod
    def validate_copy_submission(
        *,
        source_submission_id: int | None,
        target_data: dict,
        target_document: AssignedDocument | None,
        template_id: int | None,
        current_user: dict,
        db: Session,
    ) -> None:
        if source_submission_id is None:
            return

        source = SubmissionRepository(db).get(source_submission_id)
        if not source:
            raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo nguồn.")
        if (
            current_user["role"] != "admin"
            and not SubmissionRepository(db).is_active_input_assignee(
                source,
                current_user["id"],
            )
        ):
            raise HTTPException(status_code=403, detail="Bạn không có quyền nhân bản báo cáo này.")
        if target_document is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "copy_scope_mismatch", "message": "Báo cáo nhân bản phải liên kết với một PDF chưa nhập."},
            )
        if source.template_id != template_id or target_document.template_id != template_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "copy_scope_mismatch", "message": "PDF đích phải dùng cùng biểu mẫu với báo cáo nguồn."},
            )
        if source.assigned_document_id == target_document.id:
            raise HTTPException(
                status_code=409,
                detail={"code": "copy_scope_mismatch", "message": "PDF đích phải khác PDF của báo cáo nguồn."},
            )

        try:
            source_data = json.loads(source.data_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            source_data = {}
        if not isinstance(source_data, dict):
            source_data = {}

        source_folder = normalize_folder_path(source.folder_path or source_data.get("_folder_path"))
        target_folder = normalize_folder_path(target_data.get("_folder_path"))
        if not source_folder or source_folder != target_folder:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "copy_scope_mismatch",
                    "message": "PDF đích phải thuộc cùng dự án và cùng cấp hồ sơ với báo cáo nguồn.",
                },
            )

        ignored_path_field = SubmissionService._copy_linked_path_field(template_id, db)
        if not SubmissionService._copy_business_changed(source_data, target_data, ignored_path_field):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "copy_unchanged",
                    "message": "Ngoài trường đường dẫn PDF, bạn phải sửa ít nhất một trường dữ liệu so với báo cáo nguồn.",
                },
            )

    @staticmethod
    def delete_submission(db: Session, sub_id: int, current_user: dict) -> None:
        submission_repository = SubmissionRepository(db)
        sub = submission_repository.get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")

        if current_user["role"] != "admin":
            is_active_input = submission_repository.is_active_input_assignee(
                sub,
                current_user["id"],
            )
            if is_active_input and sub.status != "draft":
                raise HTTPException(status_code=409, detail="Nhân viên chỉ có thể xóa hồ sơ đang lưu nháp")
            if not is_active_input:
                raise HTTPException(status_code=403, detail="Bạn không có quyền xóa hồ sơ này")

        doc_id = sub.assigned_document_id
        ReviewRepository(db).delete_for_submissions([sub_id])
        submission_repository.delete(sub)
        db.flush()

        if doc_id:
            other_count = submission_repository.count_by_document_id(doc_id)
            if other_count == 0:
                document = DocumentRepository(db).get(doc_id)
                if document and document.status == "completed":
                    document.status = "pending"

        db.commit()

    @staticmethod
    def validate_required_fields(
        template_id: int | None,
        data: dict,
        db: Session,
        *,
        allow_missing_linked_path: bool = False,
        template_config: object = _CONTEXT_UNSET,
    ) -> None:
        if not template_id:
            return
        if template_config is _CONTEXT_UNSET:
            config = SubmissionService._template_config(
                TemplateRepository(db).get(template_id)
            )
        else:
            config = template_config if isinstance(template_config, dict) else {}
        if not config:
            return
        required_cols = config.get("required_cols", [])
        linked_path_config = config.get("linked_pdf_path") or {}
        try:
            linked_path_col = int(linked_path_config.get("col")) if allow_missing_linked_path else None
        except (TypeError, ValueError):
            linked_path_col = None
        missing = []
        for col in required_cols if isinstance(required_cols, list) else []:
            try:
                col_number = int(col)
            except (TypeError, ValueError):
                continue
            if col_number < 1:
                continue
            field_name = f"col_{col_number - 1}"
            if linked_path_col is not None and col_number == linked_path_col:
                continue
            if not str(data.get(field_name, "") or "").strip():
                missing.append(field_name)
        if missing:
            raise HTTPException(status_code=400, detail="Thiếu trường bắt buộc: " + ", ".join(missing))

    @staticmethod
    def _linked_report_path(
        template_id: int | None,
        data: dict,
        db: Session,
        *,
        template_config: object = _CONTEXT_UNSET,
    ) -> str:
        path_value = data.get("_pdf_relative_path")
        if not path_value and template_id:
            if template_config is _CONTEXT_UNSET:
                config = SubmissionService._template_config(
                    TemplateRepository(db).get(template_id)
                )
            else:
                config = template_config if isinstance(template_config, dict) else {}
            linked_path_config = config.get("linked_pdf_path") or {}
            try:
                linked_path_col = int(linked_path_config.get("col"))
            except (TypeError, ValueError):
                linked_path_col = 0
            if linked_path_col > 0:
                path_value = data.get(f"col_{linked_path_col - 1}")
        return normalize_folder_path(path_value)

    @staticmethod
    def _business_content(data: dict) -> dict:
        return {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and not key.startswith("_")
        }

    @staticmethod
    def exact_duplicate_count(
        submission: Submission,
        data: dict,
        db: Session,
        *,
        template_config: object = _CONTEXT_UNSET,
        candidates: list[Submission] | None = None,
    ) -> int:
        if template_config is _CONTEXT_UNSET:
            template_config = SubmissionService._template_config(
                TemplateRepository(db).get(submission.template_id)
            ) if submission.template_id else {}
        report_path = SubmissionService._linked_report_path(
            submission.template_id,
            data,
            db,
            template_config=template_config,
        )
        if not report_path:
            return 0
        expected_content = SubmissionService._business_content(data)
        if candidates is None:
            candidates = SubmissionRepository(db).list_exact_duplicate_candidates(
                template_id=submission.template_id,
                folder_path_key_value=submission.folder_path_key,
                exclude_submission_id=submission.id,
            )
        duplicate_count = 0
        for candidate in candidates:
            try:
                candidate_data = json.loads(candidate.data_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(candidate_data, dict):
                continue
            if SubmissionService._linked_report_path(
                candidate.template_id,
                candidate_data,
                db,
                template_config=template_config,
            ) != report_path:
                continue
            if SubmissionService._business_content(candidate_data) == expected_content:
                duplicate_count += 1
        return duplicate_count

    @staticmethod
    def lock_duplicate_scope(template_id: int | None, db: Session) -> None:
        if template_id is None:
            return
        TemplateRepository(db).lock_for_update(template_id)

    @staticmethod
    def _fetch_submission_relations(submissions: list[Submission], db: Session) -> tuple[dict, dict, dict, dict, dict]:
        document_metadata = _load_submission_document_metadata(submissions, db)
        assignment_map = ReviewRepository(db).assignment_map(submissions)
        
        user_ids = {
            submission.created_by_user_id
            for submission in submissions
            if submission.created_by_user_id is not None
        } | {
            reviewer_id for reviewer_id in assignment_map.values()
            if reviewer_id is not None
        }
        lookup_repository = LookupRepository(db)
        user_map = lookup_repository.username_map(user_ids)
        
        template_ids = {
            submission.template_id
            for submission in submissions
            if submission.template_id is not None
        }
        template_map = lookup_repository.template_name_map(template_ids)
        
        quality_map = SubmissionQualityRepository(db).map_for_submissions(
            [submission.id for submission in submissions]
        )
        return document_metadata, assignment_map, user_map, template_map, quality_map

    @staticmethod
    def _build_submission_response(
        sub: Submission, index: int, current_page: int, page_size: int,
        document_metadata: dict, assignment_map: dict, user_map: dict, template_map: dict, quality_map: dict
    ) -> dict:
        data_dict = json.loads(sub.data_json)
        metadata = document_metadata.get(sub.assigned_document_id)
        if metadata:
            document = metadata["document"]
            data_dict["_pdf_filename"] = document.original_filename
            data_dict["_pdf_uuid"] = document.uuid_filename
            data_dict["_pdf_url"] = _pdf_url(document.uuid_filename)
            if metadata["relative_path"]:
                data_dict["_pdf_relative_path"] = metadata["relative_path"]
        submission_folder = normalize_folder_path(sub.folder_path)
        if not submission_folder:
            submission_folder = COMPLETED_WITHOUT_FOLDER
            
        ho_ten = data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)"
        so_giay_to = data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)"
        template_name = template_map.get(sub.template_id, "Unknown") if sub.template_id else "Unknown"
        result_folder_path = "" if submission_folder == COMPLETED_WITHOUT_FOLDER else submission_folder
            
        quality = quality_map.get(sub.id)
        changed_field_count = int(getattr(quality, "changed_field_count", 0) or 0)
        is_error_report = bool(getattr(quality, "is_error_report", False))
        return {
            "id": sub.id,
            "serial_number": (current_page - 1) * page_size + index + 1,
            "ho_ten": ho_ten,
            "so_giay_to": so_giay_to,
            "created_at": (sub.created_at + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S") if sub.created_at else "",
            "template": template_name,
            "template_id": sub.template_id,
            "pdf_filename": data_dict.get("_pdf_filename", ""),
            "pdf_relative_path": data_dict.get("_pdf_relative_path", ""),
            "folder_path": result_folder_path,
            "folder_name": "Thư mục gốc" if result_folder_path == "__ROOT__" else result_folder_path.rstrip("/").rsplit("/", 1)[-1] if result_folder_path else "",
            "is_checked": sub.is_checked,
            "status": sub.status,
            "has_errors": bool(data_dict.get("_wrong_sections", [])),
            "quality": {
                "has_review_changes": changed_field_count > 0,
                "changed_field_count": changed_field_count,
                "visible_field_count": int(getattr(quality, "visible_field_count", 0) or 0),
                "is_error_report": is_error_report,
            },
            "creator_name": user_map.get(sub.created_by_user_id, "Unknown"),
            "reviewer_user_id": assignment_map.get(sub.id),
            "reviewer_name": user_map.get(assignment_map.get(sub.id), "Chưa phân công"),
            "reviewer_assigned": assignment_map.get(sub.id) is not None,
            "is_reviewer_assigned": assignment_map.get(sub.id) is not None,
        }

    @staticmethod
    def get_paginated_submissions_payload(
        db: Session,
        current_user: dict,
        template_id: int | None,
        start_date: str | None,
        end_date: str | None,
        status: str | None,
        folder_path: str | None,
        page: int,
        page_size: int,
        duplicate_only: bool = False,
    ) -> dict:
        repository = SubmissionRepository(db)
        if current_user["role"] == "admin":
            submissions, total, total_pages, current_page = repository.paginate(
                owner_id=None,
                status=status,
                template_id=template_id,
                start_date=start_date,
                end_date=end_date,
                folder_path=folder_path,
                page=page,
                page_size=page_size,
                duplicate_only=duplicate_only,
            )
        else:
            submissions, total, total_pages, current_page = (
                repository.paginate_for_input_user(
                    user_id=current_user["id"],
                    status=status,
                    template_id=template_id,
                    start_date=start_date,
                    end_date=end_date,
                    folder_path=folder_path,
                    page=page,
                    page_size=page_size,
                    duplicate_only=duplicate_only,
                )
            )

        document_metadata, assignment_map, user_map, template_map, quality_map = SubmissionService._fetch_submission_relations(submissions, db)
            
        results = [
            SubmissionService._build_submission_response(
                sub, index, current_page, page_size,
                document_metadata, assignment_map, user_map, template_map, quality_map
            )
            for index, sub in enumerate(submissions)
        ]

        unread_submission_ids = (
            SubmissionReviewHistoryRepository(db).unread_submission_ids(
                current_user["id"]
            )
            if current_user["role"] != "admin"
            else set()
        )
        for result in results:
            result["quality"]["is_unread"] = result["id"] in unread_submission_ids
            
        first_item = (current_page - 1) * page_size + 1 if total else 0
        return {
            "status": "ok",
            "data": results,
            "unread_review_count": len(unread_submission_ids),
            "pagination": {
                "page": current_page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "from": first_item,
                "to": first_item + len(results) - 1 if results else 0,
            },
        }

