from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from server.database import get_db
from server.routers.auth import get_current_user
from server.services.paper_handoff_service import PaperHandoffService

router = APIRouter(prefix="/api/projects/{project_id}")

class PaperHandoffIn(BaseModel):
    model_config = ConfigDict(strict=True)
    happened_at: str
    handed_by: str
    received_by: str
    note: str | None = None

@router.get("/paper-handoffs")
def get_handoffs(project_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)):
    service = PaperHandoffService(db)
    return service.get_handoffs(project_id, user)

@router.put("/cases/{case_id}/paper-handoffs/{milestone}")
def record_handoff(project_id: int, case_id: int, milestone: str, data: PaperHandoffIn, user: dict = Depends(get_current_user), db=Depends(get_db)):
    service = PaperHandoffService(db)
    res = service.record_handoff(project_id, case_id, milestone, data.model_dump(), user)
    db.commit()
    return res

@router.delete("/cases/{case_id}/paper-handoffs/{milestone}")
def delete_handoff(project_id: int, case_id: int, milestone: str, user: dict = Depends(get_current_user), db=Depends(get_db)):
    service = PaperHandoffService(db)
    res = service.delete_handoff(project_id, case_id, milestone, user)
    db.commit()
    return res

@router.get("/paper-handoffs.xlsx")
def export_excel(project_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)):
    service = PaperHandoffService(db)
    output = service.export_excel(project_id, user)
    
    filename = f"so_giao_nhan_ho_so_giay_{project_id}.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )
