"""Export OCR suggestions paired with completed submissions for one project."""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from server.database import SessionLocal
from server.models import ProjectDocumentAsset, Submission
from server.services.document_ocr_service import normalized


COLUMNS = (
    "submission", "pipeline", "method", "processing_seconds", "wait_seconds",
    "open_to_save_seconds", "field", "confidence", "suggested", "reviewed", "changed",
)


def export(project_id, output):
    query = (
        select(Submission.id, Submission.data_json)
        .join(ProjectDocumentAsset, ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id)
        .where(ProjectDocumentAsset.project_id == project_id, Submission.status == "completed")
        .order_by(Submission.id)
    )
    with SessionLocal() as db, output.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for submission_id, payload in db.execute(query):
            values = json.loads(payload or "{}")
            trace = values.get("_ocr_experiment")
            if not isinstance(trace, dict) or trace.get("uuid") != values.get("_pdf_uuid"):
                continue
            suggestions = trace.get("suggested")
            if not isinstance(suggestions, dict):
                continue
            for column, suggestion in suggestions.items():
                if not isinstance(suggestion, dict) or column not in values:
                    continue
                initial = str(suggestion.get("value") or "")
                reviewed = str(values[column] or "")
                writer.writerow(dict(
                    submission=submission_id, pipeline=trace.get("pipeline"),
                    method=trace.get("method"), processing_seconds=trace.get("seconds"),
                    wait_seconds=trace.get("wait_seconds"), open_to_save_seconds=trace.get("open_to_save_seconds"),
                    field=suggestion.get("field"), confidence=suggestion.get("confidence"),
                    suggested=initial, reviewed=reviewed,
                    changed=int(normalized(initial) != normalized(reviewed)),
                ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.project_id, args.output)


if __name__ == "__main__":
    main()
