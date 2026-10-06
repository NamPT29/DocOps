import json
import pytest
from dataclasses import dataclass
from server.services.scan_catalog_match_service import match_scan_files_to_catalog
from sqlalchemy import create_engine, inspect

@dataclass
class DummyRow:
    dossier_number: int
    dossier_suffix: str

def test_match_perfect():
    catalog = [DummyRow(12, ""), DummyRow(12, "a")]
    files = ["0012/1.pdf", "12A/2.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "matched"
    summary = json.loads(res["summary"])
    assert summary["matched"] == ["12", "12a"]
    assert not summary["missing"]
    assert not summary["extra"]

def test_missing_dossier():
    catalog = [DummyRow(1, ""), DummyRow(2, "")]
    files = ["01/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["missing"] == ["2"]
    assert summary["matched"] == ["1"]

def test_extra_folder():
    catalog = [DummyRow(1, "")]
    files = ["01/1.pdf", "02/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["extra"] == ["02"]
    assert summary["matched"] == ["1"]

def test_invalid_folder():
    catalog = [DummyRow(1, "")]
    files = ["01/1.pdf", "ABC/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["invalid_folders"] == ["ABC"]
    assert summary["matched"] == ["1"]

def test_duplicate_folder():
    catalog = [DummyRow(1, "")]
    files = ["1/1.pdf", "01/2.pdf", "001/3.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["matched"] == ["1"]
    # The first one "1" gets matched, "01" and "001" are duplicates
    # Since dict iterating order depends on insertion which depends on files processing order,
    # "01" and "001" will be the duplicates.
    assert set(summary["duplicate_folders"]) == {"01", "001"}

def test_pdf_at_box_root():
    catalog = [DummyRow(1, "")]
    files = ["1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["misplaced_files"] == ["1.pdf"]
    assert summary["missing"] == ["1"]

def test_pdf_too_deep():
    catalog = [DummyRow(1, "")]
    files = ["01/sub/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["misplaced_files"] == ["01/sub/1.pdf"]
    assert summary["missing"] == ["1"]

def test_only_cover():
    catalog = [DummyRow(1, "")]
    files = ["01/BIA.pdf", "01/bia_phu.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["only_cover"] == ["01"]
    assert summary["missing"] == ["1"]

def test_removed_from_catalog():
    catalog = [DummyRow(1, "")]
    removed = [DummyRow(2, "")]
    files = ["01/1.pdf", "02/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files, removed_rows=removed)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["removed_from_catalog"] == ["02"]
    assert summary["extra"] == []

def test_no_catalog():
    catalog = []
    files = ["01/1.pdf"]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "no_catalog"
    summary = json.loads(res["summary"])
    assert summary["catalog_total"] == 0

def test_truncated():
    catalog = [DummyRow(1, "")]
    files = [f"extra{i}/1.pdf" for i in range(100)]
    res = match_scan_files_to_catalog(catalog, files)
    assert res["match_status"] == "mismatch"
    summary = json.loads(res["summary"])
    assert summary["truncated"] is True
    assert len(summary["invalid_folders"]) == 50

def test_migration_0012(tmp_path):
    from alembic.config import Config
    from alembic import command
    from pathlib import Path
    
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    
    base_dir = Path(__file__).parent.parent
    alembic_cfg = Config(str(base_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(base_dir / "migrations"))
    alembic_cfg.attributes["connection"] = engine
    
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "0012_scan_catalog_match")
        
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("case_scan_packages")}
    assert "match_status" in columns
    assert "match_summary" in columns
