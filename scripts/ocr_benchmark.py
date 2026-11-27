"""Run locally: python scripts/ocr_benchmark.py labels.csv results.csv

Labels use UTF-8 CSV: pdf (relative to CSV), typeName, code, issuedDate,
organName, subject. Install requirements-ocr.txt first. Run output contains
raw OCR text; retain it locally with the source documents.
"""
import argparse
import csv
import gzip
import re
import shutil
import statistics
import tempfile
import time
import unicodedata
from datetime import date
from pathlib import Path

FIELDS = ("typeName", "code", "issuedDate", "organName", "subject")
TYPES = ("Quyết định", "Báo cáo", "Thông báo", "Tờ trình", "Kế hoạch", "Biên bản", "Nghị quyết", "Chỉ thị")
LANG = Path(__file__).resolve().parents[1] / "frontend/vendor/tesseract/lang/vie.traineddata.gz"


def normalized(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def title_key(value):
    return "".join(c for c in unicodedata.normalize("NFD", normalized(value)) if not unicodedata.combining(c))


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def extract_fields(text):
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    result = dict.fromkeys(FIELDS, "")
    code = re.search(r"(?im)^\s*S[ốôo]\s*[:.]?\s*(\d+\s*/\s*[\wĐđ-]+)", text)
    if code:
        result["code"] = re.sub(r"\s+", "", code[1])
    day = re.search(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", text, re.I)
    if day:
        try:
            result["issuedDate"] = date(int(day[3]), int(day[2]), int(day[1])).strftime("%d/%m/%Y")
        except ValueError:
            pass
    for line in lines:
        agency = re.split(r"CỘNG\s+H[ÒO]A|Độc lập", line, flags=re.I)[0].strip(" |-")
        if re.match(r"^(ỦY BAN|UỶ BAN|UBND|BỘ |SỞ |PHÒNG |TRƯỜNG |VĂN PHÒNG)", agency, re.I):
            result["organName"] = agency
    for i, line in enumerate(lines):
        for name in TYPES:
            if title_key(line) == title_key(name):
                result["typeName"] = name
                if i + 1 < len(lines):
                    result["subject"] = lines[i + 1]
                return result
    for line in lines:
        subject = re.match(r"V\s*/\s*v\s*[:.]?\s*(.+)", line, re.I)
        if subject:
            result.update(typeName="Công văn", subject=subject[1].strip())
            break
    return result


def read_header(path, api):
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(path) as document:
        page = document[0]
        try:
            bitmap = page.render(scale=200 / 72, crop=(0, page.get_height() * 0.58, 0, 0))
            try:
                api.SetImage(bitmap.to_pil())
                return api.GetUTF8Text().strip()
            finally:
                bitmap.close()
        finally:
            page.close()


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
    with tempfile.TemporaryDirectory() as directory:
        with gzip.open(LANG, "rb") as compressed, open(Path(directory) / "vie.traineddata", "wb") as model:
            shutil.copyfileobj(compressed, model)
        with tesserocr.PyTessBaseAPI(path=directory, lang="vie", psm=tesserocr.PSM.AUTO) as api:
            for sample in samples:
                start = time.perf_counter()
                raw, error = "", ""
                try:
                    api.ClearAdaptiveClassifier()
                    raw = read_header(args.labels.parent / sample["pdf"], api)
                except (OSError, RuntimeError, ValueError, IndexError) as exc:
                    error = str(exc)
                guessed = extract_fields(raw)
                row = dict(pdf=sample["pdf"], seconds=round(time.perf_counter()-start, 3), error=error, raw=raw)
                for field in FIELDS:
                    expected = sample[field]
                    row[field] = guessed[field]
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
    print("Median seconds:", statistics.median(row["seconds"] for row in results))
    if reference_chars:
        print("Normalized header CER:", char_errors / reference_chars)
    return int(any(row["error"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
