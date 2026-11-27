"""Export the latest saved UBND form for each document in a local entry study."""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from server.database import SessionLocal
from server.models import AssignedDocument, Submission, Template, User
from server.services.document_ocr_service import normalized


def build_row(sample, document, values):
    entry = values.get("_entry_experiment") or {}
    ocr = values.get("_ocr_experiment") or {}
    measured = entry.get("uuid") == document
    suggestions = ocr.get("suggested", {}) if ocr.get("uuid") == document else {}
    attempted = entry.get("header_ocr_attempted") if measured else None
    changed = sum(
        normalized(str(item.get("value") or "")) != normalized(str(values.get(column) or ""))
        for column, item in suggestions.items()
    )
    number, notation = (str(values.get(column) or "").strip() for column in ("col_15", "col_16"))
    row = dict(sample)
    row.update(
        seconds=entry.get("open_to_save_seconds") if measured else "",
        typeName=values.get("col_18", ""),
        code="/".join(part for part in (number, notation) if part),
        issuedDate=values.get("col_17", ""),
        organName=values.get("col_14", ""),
        subject=values.get("col_20", ""),
        header_ocr_attempted=attempted if measured else "",
        suggestions=len(suggestions),
        suggestions_changed=changed,
        initial_suggestions=json.dumps(suggestions, ensure_ascii=False),
    )
    if not values:
        row["measurement_status"] = "not_saved"
    elif not measured:
        row["measurement_status"] = "missing_timing"
    elif attempted != (sample["mode"] == "ocr"):
        row["measurement_status"] = "mode_mismatch"
    elif attempted and not suggestions:
        row["measurement_status"] = "ocr_no_suggestions"
    else:
        row["measurement_status"] = "recorded"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.plan.open(encoding="utf-8-sig", newline="") as stream:
        plan = list(csv.DictReader(stream))
    if not plan or any(row.get("mode") not in {"manual", "ocr"} for row in plan):
        parser.error("Provide a nonempty entry plan with manual or ocr modes.")

    query = (
        select(AssignedDocument.uuid_filename, Submission.data_json)
        .join(Submission, Submission.assigned_document_id == AssignedDocument.id)
        .join(User, User.id == Submission.created_by_user_id)
        .join(Template, Template.id == Submission.template_id)
        .where(User.username == args.username, Template.filename == "UBND.xlsx")
        .order_by(Submission.id)
    )
    with SessionLocal() as db:
        saved = {name: json.loads(payload) for name, payload in db.execute(query)}
    rows = []
    for sample in plan:
        document = f"{int(sample['order']):02d}-{sample['id']}-{Path(sample['pdf']).name}"
        rows.append(build_row(sample, document, saved.get(document, {})))
    with args.output.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
