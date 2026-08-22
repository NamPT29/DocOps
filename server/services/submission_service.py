from server.services.submission_helpers import COMPLETED_WITHOUT_FOLDER, _pdf_url
from server.services.submission_metadata_service import apply_submission_metadata

from typing import Literal
from fastapi import HTTPException
import os
import json
from datetime import timedelta
from sqlalchemy.orm import Session

from server.models import Submission, AssignedDocument
from server.repositories import (
    DocumentRepository,
    LookupRepository,
    ReviewRepository,
    SubmissionRepository,
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
    ) -> None:
        folder_path = normalize_folder_path(data.get("_folder_path"))
        if not folder_path and document:
            folder_metadata = DocumentRepository(db).get_folder(document.id)
            folder_path = normalize_folder_path(
                getattr(folder_metadata, "folder_group", None)
            )
        apply_submission_metadata(
            submission,
            data,
            document=document,
            folder_path=folder_path,
        )


    @staticmethod
    def bulk_submission_action(
        db: Session,
        action: Literal["delete"],
        submission_ids: list[int],
        current_user: dict
    ) -> int:
        submission_repository = SubmissionRepository(db)
        selected = submission_repository.list_by_ids(submission_ids)
        if len(selected) != len(submission_ids):
            raise HTTPException(status_code=404, detail="Có hồ sơ không tồn tại")
        if current_user["role"] != "admin" and any(
            submission.created_by_user_id != current_user["id"]
            for submission in selected
        ):
            raise HTTPException(status_code=403, detail="Bạn không có quyền xử lý một hoặc nhiều hồ sơ đã chọn")

        if action != "delete":
            raise HTTPException(status_code=409, detail="Nộp duyệt hàng loạt đã bị tắt")
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
            for doc_id in doc_ids:
                other_count = submission_counts.get(doc_id, 0)
                if other_count == 0:
                    document = doc_repo.get(doc_id)
                    if document and document.status == "completed":
                        document.status = "pending"

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
            }
            for item, relative_path, submission_id in rows
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
        allow_unregistered: bool = False,
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
            uuid_filename = os.path.basename(str(enriched["_pdf_uuid"]))
            if not allow_unregistered:
                raise HTTPException(status_code=400, detail="File đính kèm không thuộc người dùng")
            enriched["_pdf_uuid"] = uuid_filename
            enriched["_pdf_url"] = _pdf_url(uuid_filename)
        elif enriched.get("_pdf_filename") and not allow_unregistered:
            raise HTTPException(status_code=400, detail="Không xác minh được file đính kèm")
        return enriched, document

    @staticmethod
    def delete_submission(db: Session, sub_id: int, current_user: dict) -> None:
        submission_repository = SubmissionRepository(db)
        sub = submission_repository.get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")

        if current_user["role"] != "admin":
            is_creator = sub.created_by_user_id == current_user["id"]
            if is_creator and sub.status != "draft":
                raise HTTPException(status_code=409, detail="Nhân viên chỉ có thể xóa hồ sơ đang lưu nháp")
            if not is_creator:
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
    def copy_submission(db: Session, sub_id: int, current_user: dict) -> int:
        from datetime import datetime, timezone
        repository = SubmissionRepository(db)
        sub = repository.get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền nhân bản hồ sơ này.")
        
        new_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        new_sub = Submission(
            data_json=sub.data_json,
            template_id=sub.template_id,
            created_at=new_created_at,
            created_by_user_id=current_user["id"],
            assigned_document_id=sub.assigned_document_id,
            folder_path=sub.folder_path,
            folder_path_key=sub.folder_path_key,
        )
        repository.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        return new_sub.id

    @staticmethod
    def validate_required_fields(
        template_id: int | None,
        data: dict,
        db: Session,
        *,
        allow_missing_linked_path: bool = False,
    ) -> None:
        if not template_id:
            return
        template = TemplateRepository(db).get(template_id)
        if not template or not template.config_json:
            return
        try:
            config = json.loads(template.config_json)
        except (TypeError, ValueError):
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
    def _linked_report_path(template_id: int | None, data: dict, db: Session) -> str:
        path_value = data.get("_pdf_relative_path")
        if not path_value and template_id:
            template = TemplateRepository(db).get(template_id)
            if template and template.config_json:
                try:
                    config = json.loads(template.config_json)
                except (TypeError, ValueError, json.JSONDecodeError):
                    config = {}
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
    ) -> int:
        report_path = SubmissionService._linked_report_path(
            submission.template_id,
            data,
            db,
        )
        if not report_path:
            return 0
        expected_content = SubmissionService._business_content(data)
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
    def normalize_wrong_fields(values: list[str] | None) -> list[str]:
        normalized = []
        for value in values or []:
            if not isinstance(value, str):
                continue
            field_name = value.strip()
            if not field_name or field_name.startswith("_") or field_name in normalized:
                continue
            normalized.append(field_name)
        return normalized

    @staticmethod
    def _fetch_submission_relations(submissions: list[Submission], db: Session) -> tuple[dict, dict, dict, dict]:
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
        
        return document_metadata, assignment_map, user_map, template_map

    @staticmethod
    def _build_submission_response(
        sub: Submission, index: int, current_page: int, page_size: int,
        document_metadata: dict, assignment_map: dict, user_map: dict, template_map: dict
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
        elif data_dict.get("_pdf_uuid"):
            uuid_filename = os.path.basename(str(data_dict["_pdf_uuid"]))
            data_dict["_pdf_uuid"] = uuid_filename
            data_dict["_pdf_url"] = _pdf_url(uuid_filename)
            
        submission_folder = normalize_folder_path(sub.folder_path)
        if not submission_folder:
            submission_folder = COMPLETED_WITHOUT_FOLDER
            
        ho_ten = data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)"
        so_giay_to = data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)"
        template_name = template_map.get(sub.template_id, "Unknown") if sub.template_id else "Unknown"
        result_folder_path = "" if submission_folder == COMPLETED_WITHOUT_FOLDER else submission_folder
            
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
            "has_errors": (
                sub.status == "rejected"
                or bool(data_dict.get("_wrong_sections", []))
                or bool(data_dict.get("_wrong_fields", []))
            ),
            "creator_name": user_map.get(sub.created_by_user_id, "Unknown"),
            "reviewer_name": user_map.get(assignment_map.get(sub.id), "Chưa phân công"),
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
        submissions, total, total_pages, current_page = repository.paginate(
            owner_id=(None if current_user["role"] == "admin" else current_user["id"]),
            status=status,
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            folder_path=folder_path,
            page=page,
            page_size=page_size,
            duplicate_only=duplicate_only,
        )

        document_metadata, assignment_map, user_map, template_map = SubmissionService._fetch_submission_relations(submissions, db)
            
        results = [
            SubmissionService._build_submission_response(
                sub, index, current_page, page_size,
                document_metadata, assignment_map, user_map, template_map
            )
            for index, sub in enumerate(submissions)
        ]
            
        first_item = (current_page - 1) * page_size + 1 if total else 0
        return {
            "status": "ok",
            "data": results,
            "pagination": {
                "page": current_page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "from": first_item,
                "to": first_item + len(results) - 1 if results else 0,
            },
        }

