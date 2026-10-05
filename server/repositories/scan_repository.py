from sqlalchemy.orm import Session
from server.models import Project, ProjectCase, User
from server.models_scan import CaseScanPackage, CaseScanFile
from server.models_workflow import ProjectStageMember
from server.database import get_utc_now


def get_project_by_id(db: Session, project_id: int) -> Project | None:
    return db.query(Project).filter(Project.id == project_id).first()


def get_case_by_id(db: Session, project_id: int, case_id: int) -> ProjectCase | None:
    return db.query(ProjectCase).filter(
        ProjectCase.id == case_id,
        ProjectCase.project_id == project_id
    ).first()


def get_users_by_ids(db: Session, user_ids: list[int]) -> list[User]:
    if not user_ids:
        return []
    return db.query(User).filter(User.id.in_(user_ids)).all()


def get_scan_stage_member_ids(db: Session, project_id: int) -> list[int]:
    return [
        m.user_id for m in db.query(ProjectStageMember).filter_by(
            project_id=project_id, stage_key="scan"
        ).all()
    ]


def update_assigned_user_for_scan_stage(db: Session, case_id: int, assigned_user_id: int | None):
    from sqlalchemy import text
    db.execute(
        text("""
        UPDATE case_stage_states 
        SET assigned_user_id = :assigned
        WHERE case_id = :case_id AND stage_key = 'scan'
        """),
        {"assigned": assigned_user_id, "case_id": case_id}
    )


def lock_and_get_latest_scan_package_version(db: Session, case_id: int) -> int:
    last_pkg = db.query(CaseScanPackage).with_for_update().filter(
        CaseScanPackage.case_id == case_id
    ).order_by(CaseScanPackage.version.desc()).first()
    return (last_pkg.version + 1) if last_pkg else 1


def get_processing_scan_package(db: Session, case_id: int) -> CaseScanPackage | None:
    return db.query(CaseScanPackage).filter(
        CaseScanPackage.case_id == case_id,
        CaseScanPackage.status == "processing"
    ).first()


def create_scan_package(db: Session, pkg: CaseScanPackage) -> CaseScanPackage:
    db.add(pkg)
    db.flush()
    return pkg


def list_scan_packages(db: Session, case_id: int) -> list[CaseScanPackage]:
    return db.query(CaseScanPackage).filter(
        CaseScanPackage.case_id == case_id
    ).order_by(CaseScanPackage.version.desc()).all()


def get_scan_package(db: Session, package_id: int) -> CaseScanPackage | None:
    return db.query(CaseScanPackage).filter(
        CaseScanPackage.id == package_id
    ).first()


def create_scan_files(db: Session, files: list[CaseScanFile]):
    db.add_all(files)
    db.flush()


def update_scan_package(db: Session, package: CaseScanPackage):
    # SQLAlchemy tracking handles this, just flush
    db.flush()


def delete_stuck_processing_packages(db: Session):
    # Đổi tên hàm thành resolve_stuck_processing_packages nhưng gọi là delete_stuck_processing_packages
    # theo yêu cầu cũ (chưa cần thiết phải đổi tên nếu gọi từ main.py, nhưng ta có thể giữ nguyên).
    # Chuyển status = 'processing' -> 'failed', kèm reason.
    db.query(CaseScanPackage).filter(CaseScanPackage.status == 'processing').update(
        {
            CaseScanPackage.status: 'failed',
            CaseScanPackage.error_message: 'Hệ thống bị tắt đột ngột khi đang xử lý'
        }
    )
    db.flush()
