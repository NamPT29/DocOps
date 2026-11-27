"""Run locally: python scripts/ocr_benchmark.py labels.csv results.csv

Labels use UTF-8 CSV: pdf (relative to CSV), typeName, code, issuedDate,
organName, subject. Install requirements-ocr.txt first. Run output contains
raw OCR text; retain it locally with the source documents.
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.services.document_ocr_service import FIELDS, PIPELINE_VERSION, extract_fields, normalized, recognize_document


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def main():
    import tesserocr

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.labels.resolve() == args.output.resolve():
        parser.error("Choose a separate output CSV")
    with args.labels.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not {"pdf", *FIELDS}.issubset(reader.fieldnames or []):
            parser.error("Missing required label columns")
        samples = list(reader)
    if not samples:
        parser.error("Empty dataset")
    results = []
    char_errors = reference_chars = 0
    for sample in samples:
        error = ""
        try:
            result = recognize_document(args.labels.parent / sample["pdf"])
        except (OSError, RuntimeError, ValueError, IndexError) as exc:
            error = str(exc)
            result = dict(raw="", fields=dict.fromkeys(FIELDS, ""), seconds="", method="", pipeline=PIPELINE_VERSION)
        raw = result["raw"]
        guessed = result["fields"]
        row = dict(pdf=sample["pdf"], seconds=result["seconds"], method=result["method"],
                   pipeline=result["pipeline"], engine=tesserocr.tesseract_version().splitlines()[0],
                   error=error, raw=raw)
        for field in FIELDS:
            expected = sample[field]
            row[field] = guessed[field]
            row[field + "_confidence"] = result.get("field_confidence", {}).get(field)
            row[field + "_expected"] = expected
            row[field + "_correct"] = int(not error and normalized(expected) == normalized(guessed[field])) if expected.strip() else ""
        reference = normalized(sample.get("header_text") or "")
        if reference:
            errors = edit_distance(reference, normalized(raw))
            char_errors += errors
            reference_chars += len(reference)
            row["cer"] = errors / len(reference)
        else:
            row["cer"] = ""
        subject = normalized(sample["subject"])
        prediction = normalized(guessed["subject"])
        row["subject_similarity"] = 1 - edit_distance(subject, prediction) / max(len(subject), len(prediction)) if subject else ""
        results.append(row)
    with args.output.open("w", encoding="utf-8-sig", newline="") as dest:
        writer = csv.DictWriter(dest, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)
    print(tesserocr.tesseract_version().splitlines()[0])
    for field in FIELDS:
        scores = [row[field + "_correct"] for row in results if row[field + "_correct"] != ""]
        print(field, f"{sum(scores)}/{len(scores)}")
    timings = [row["seconds"] for row in results if row["seconds"] != ""]
    if timings:
        print("Median seconds:", statistics.median(timings))
        print("Over 5 seconds:", sum(value > 5 for value in timings), "/", len(timings))
    if reference_chars:
        print("Normalized header CER:", char_errors / reference_chars)
    return int(any(row["error"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
