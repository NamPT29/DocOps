import io
import re
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from server.repositories.paper_handoff_repository import PaperHandoffRepository
from server.repositories.workflow_repository import WorkflowRepository
from server.database import get_utc_now
from server.models_paper import CasePaperHandoff
from server.services.arrangement_catalog_parser import box_number_of_case_key
from server.services.normalization_plan_service import natural_key
import openpyxl

MILESTONES = [
    {"key": "received_from_client", "label": "Nhận từ khách hàng", "order": 1},
    {"key": "to_arrangement", "label": "Giao chỉnh lý", "order": 2},
    {"key": "to_scan", "label": "Giao scan", "order": 3},
    {"key": "returned_to_storage", "label": "Trả kho", "order": 4},
    {"key": "returned_to_client", "label": "Trả khách hàng", "order": 5},
]

MILESTONE_KEYS = [m["key"] for m in MILESTONES]
MILESTONE_DICT = {m["key"]: m for m in MILESTONES}


class PaperHandoffService:
    def __init__(self, db_session):
        self.repo = PaperHandoffRepository(db_session)
        self.workflow_repo = WorkflowRepository(db_session)

    def _check_auth(self, project_id: int, user: dict):
        db_user = self.repo.get_user_by_id(user["id"])
        if not db_user:
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Không có quyền"})
        if db_user.account_type == "ctv":
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "CTV không có quyền truy cập sổ giao nhận."})
        if user.get("role") == "admin":
            return
        is_arr = self.workflow_repo.user_is_stage_member(project_id, user["id"], "arrangement")
        is_scan = self.workflow_repo.user_is_stage_member(project_id, user["id"], "scan")
        if not is_arr and not is_scan:
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Bạn không thuộc bước chỉnh lý hoặc scan của dự án này."})

    def get_handoffs(self, project_id: int, user: dict):
        project = self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})

        self._check_auth(project_id, user)

        cases = self.repo.get_cases_for_project(project_id)
        handoffs = self.repo.get_handoffs_for_project(project_id)

        # Build user dictionary for recorded_by
        user_ids = {h.recorded_by_user_id for h in handoffs if h.recorded_by_user_id}
        users_dict = self.workflow_repo.users_by_ids(list(user_ids))

        # Sort cases
        def case_sort_key(c):
            box = box_number_of_case_key(c.case_key)
            return (1 if box is None else 0, box, natural_key(c.display_name or ""))

        cases_sorted = sorted(cases, key=case_sort_key)

        handoffs_by_case = {}
        for h in handoffs:
            if h.case_id not in handoffs_by_case:
                handoffs_by_case[h.case_id] = {}
            
            recorded_by_name = None
            if h.recorded_by_user_id in users_dict:
                u = users_dict[h.recorded_by_user_id]
                recorded_by_name = u.full_name or u.username
            
            handoffs_by_case[h.case_id][h.milestone] = {
                "happened_at": h.happened_at.isoformat() + "Z",
                "handed_by": h.handed_by,
                "received_by": h.received_by,
                "note": h.note,
                "recorded_by": recorded_by_name,
                "updated_at": h.updated_at.isoformat() + "Z"
            }

        cases_data = []
        for c in cases_sorted:
            cases_data.append({
                "case_id": c.id,
                "case_name": c.display_name,
                "box_number": box_number_of_case_key(c.case_key),
                "events": handoffs_by_case.get(c.id, {})
            })

        return {
            "status": "ok",
            "data": {
                "milestones": MILESTONES,
                "cases": cases_data
            }
        }

    def record_handoff(self, project_id: int, case_id: int, milestone: str, data: dict, user: dict):
        project = self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})
        
        self._check_auth(project_id, user)
        
        case = self.repo.get_case(project_id, case_id)
        if not case:
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "message": "Hộp không thuộc dự án"})
        if milestone not in MILESTONE_KEYS:
            raise HTTPException(status_code=404, detail={"code": "milestone_not_found", "message": "Mốc giao nhận không hợp lệ"})

        handed_by = (data.get("handed_by") or "").strip()
        received_by = (data.get("received_by") or "").strip()
        note = data.get("note")
        if isinstance(note, str):
            note = note.strip()
        if not note:
            note = None

        if not handed_by or not received_by:
            raise HTTPException(status_code=400, detail={"code": "person_required", "message": "Thiếu người giao hoặc người nhận"})
        if len(handed_by) > 255 or len(received_by) > 255:
            raise HTTPException(status_code=400, detail={"code": "text_too_long", "message": "Người giao/nhận quá dài"})
        if note and len(note) > 1000:
            raise HTTPException(status_code=400, detail={"code": "text_too_long", "message": "Ghi chú quá dài"})

        happened_at = data.get("happened_at")
        if not happened_at:
            raise HTTPException(status_code=400, detail={"code": "invalid_time", "message": "Thiếu thời gian"})

        if isinstance(happened_at, str):
            try:
                dt = datetime.fromisoformat(happened_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    raise HTTPException(status_code=400, detail={"code": "timezone_required", "message": "Thiếu múi giờ trong happened_at"})
                # Convert to naive UTC
                happened_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                raise HTTPException(status_code=400, detail={"code": "invalid_time", "message": "happened_at không hợp lệ"})

        now_utc = get_utc_now()
        if happened_at > now_utc + timedelta(minutes=5):
            raise HTTPException(status_code=400, detail={"code": "future_time", "message": "Thời gian không được lớn hơn hiện tại quá 5 phút"})

        idx = MILESTONE_KEYS.index(milestone)
        all_handoffs = self.repo.get_handoffs_for_case(case_id)
        handoffs_dict = {h.milestone: h for h in all_handoffs}

        if idx > 0:
            prev_milestone = MILESTONE_KEYS[idx - 1]
            if prev_milestone not in handoffs_dict:
                prev_label = MILESTONE_DICT[prev_milestone]["label"]
                raise HTTPException(status_code=409, detail={"code": "previous_milestone_missing", "message": f"Chưa ghi mốc «{prev_label}»"})
            if happened_at < handoffs_dict[prev_milestone].happened_at:
                raise HTTPException(status_code=409, detail={"code": "milestone_before_previous", "message": "Thời gian sớm hơn mốc trước đó"})

        if idx < len(MILESTONE_KEYS) - 1:
            next_milestone = MILESTONE_KEYS[idx + 1]
            if next_milestone in handoffs_dict:
                if happened_at > handoffs_dict[next_milestone].happened_at:
                    raise HTTPException(status_code=409, detail={"code": "milestone_after_next", "message": "Thời gian muộn hơn mốc sau đó"})

        handoff = handoffs_dict.get(milestone)
        if handoff:
            handoff.happened_at = happened_at
            handoff.handed_by = handed_by
            handoff.received_by = received_by
            handoff.note = note
            handoff.recorded_by_user_id = user["id"]
            handoff.updated_at = now_utc
        else:
            handoff = CasePaperHandoff(
                project_id=project_id,
                case_id=case_id,
                milestone=milestone,
                happened_at=happened_at,
                handed_by=handed_by,
                received_by=received_by,
                note=note,
                recorded_by_user_id=user["id"]
            )
            self.repo.add_handoff(handoff)

        recorded_by_name = None
        db_user = self.repo.get_user_by_id(user["id"])
        if db_user:
            recorded_by_name = db_user.full_name or db_user.username

        return {
            "status": "ok",
            "data": {
                "happened_at": handoff.happened_at.isoformat() + "Z",
                "handed_by": handoff.handed_by,
                "received_by": handoff.received_by,
                "note": handoff.note,
                "recorded_by": recorded_by_name,
                "updated_at": (handoff.updated_at or now_utc).isoformat() + "Z"
            }
        }

    def delete_handoff(self, project_id: int, case_id: int, milestone: str, user: dict):
        project = self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})
            
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Chỉ Admin mới được xóa"})

        case = self.repo.get_case(project_id, case_id)
        if not case:
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "message": "Hộp không thuộc dự án"})
        if milestone not in MILESTONE_KEYS:
            raise HTTPException(status_code=404, detail={"code": "milestone_not_found", "message": "Mốc giao nhận không hợp lệ"})

        all_handoffs = self.repo.get_handoffs_for_case(case_id)
        handoffs_dict = {h.milestone: h for h in all_handoffs}

        if milestone not in handoffs_dict:
            return {"status": "ok"} # Already deleted or not exists

        max_idx = -1
        for m in MILESTONE_KEYS:
            if m in handoffs_dict:
                max_idx = MILESTONE_KEYS.index(m)

        idx = MILESTONE_KEYS.index(milestone)
        if idx != max_idx:
            raise HTTPException(status_code=409, detail={"code": "not_last_milestone", "message": "Chỉ được xóa mốc cuối cùng"})

        self.repo.delete_handoff(handoffs_dict[milestone])
        return {"status": "ok"}

    def export_excel(self, project_id: int, user: dict):
        project = self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})

        self._check_auth(project_id, user)

        cases = self.repo.get_cases_for_project(project_id)
        handoffs = self.repo.get_handoffs_for_project(project_id)

        def case_sort_key(c):
            box = box_number_of_case_key(c.case_key)
            return (1 if box is None else 0, box, natural_key(c.display_name or ""))

        cases_sorted = sorted(cases, key=case_sort_key)
        
        handoffs_by_case = {}
        for h in handoffs:
            if h.case_id not in handoffs_by_case:
                handoffs_by_case[h.case_id] = {}
            handoffs_by_case[h.case_id][h.milestone] = h

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sổ giao nhận"

        headers = ["Hộp"]
        for m in MILESTONES:
            headers.extend([f"{m['label']} - Thời gian", f"{m['label']} - Người giao", f"{m['label']} - Người nhận"])
        headers.append("Ghi chú")

        ws.append(headers)

        for c in cases_sorted:
            row = [c.display_name or ""]
            case_handoffs = handoffs_by_case.get(c.id, {})
            notes = []
            for m in MILESTONES:
                h = case_handoffs.get(m["key"])
                if h:
                    # Convert UTC to VN time (UTC+7)
                    vn_time = h.happened_at + timedelta(hours=7)
                    time_str = vn_time.strftime("%d/%m/%Y %H:%M")
                    row.extend([time_str, h.handed_by, h.received_by])
                    if h.note:
                        notes.append(f"{m['label']}: {h.note}")
                else:
                    row.extend(["", "", ""])
            row.append("\n".join(notes))
            ws.append(row)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output
