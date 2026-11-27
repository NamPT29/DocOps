from contextlib import closing
from functools import lru_cache
import gzip
from pathlib import Path
import re
import tempfile
from threading import Lock
import time
import unicodedata
from datetime import date

FIELDS = ("typeName", "code", "issuedDate", "organName", "subject")
TYPES = ("Quyết định", "Báo cáo", "Thông báo", "Tờ trình", "Kế hoạch", "Biên bản", "Nghị quyết", "Chỉ thị")
LANG = Path(__file__).resolve().parents[2] / "frontend/vendor/tesseract/lang/vie.traineddata.gz"


def normalized(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def title_key(value):
    return "".join(c for c in unicodedata.normalize("NFD", normalized(value)) if not unicodedata.combining(c))


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



PDF_LOCK = Lock()
PIPELINE_VERSION = "docops-vie-header-v1"


@lru_cache(maxsize=1)
def model_directory():
    directory = tempfile.TemporaryDirectory(prefix="docops-ocr-")
    (Path(directory.name) / "vie.traineddata").write_bytes(gzip.decompress(LANG.read_bytes()))
    return directory


def recognize_document(path):
    import pypdfium2 as pdfium

    start = time.perf_counter()
    word_scores = {}
    with PDF_LOCK, pdfium.PdfDocument(path) as document:
        with closing(document[0]) as page:
            bottom = page.get_height() * 0.58
            with closing(page.get_textpage()) as layer:
                raw = layer.get_text_bounded(0, bottom, page.get_width(), page.get_height()).strip()
            method = "text_layer"
            confidence = None
            if not raw:
                import tesserocr

                method = "tesseract"
                scale = min(200 / 72, 3200 / max(page.get_width(), page.get_height()))
                with closing(page.render(scale=scale, crop=(0, bottom, 0, 0))) as bitmap:
                    with tesserocr.PyTessBaseAPI(
                        path=model_directory().name, lang="vie", psm=tesserocr.PSM.AUTO
                    ) as engine:
                        engine.SetImage(bitmap.to_pil())
                        raw = engine.GetUTF8Text().strip()
                        confidence = max(0, min(100, engine.MeanTextConf()))
                        iterator = engine.GetIterator()
                        if iterator:
                            level = tesserocr.RIL.WORD
                            for word in tesserocr.iterate_level(iterator, level):
                                key = title_key(word.GetUTF8Text(level) or "").strip(".,:;")
                                if key:
                                    score = max(0, min(100, word.Confidence(level)))
                                    word_scores[key] = min(score, word_scores.get(key, score))
    values = extract_fields(raw)
    number, separator, notation = values["code"].partition("/")
    values.update(codeNumber=number, codeNotation=notation if separator else "")
    field_confidence = {}
    for field, value in values.items():
        tokens = title_key(value).split()
        scores = [word_scores[token] for token in tokens if token in word_scores]
        field_confidence[field] = round(min(scores)) if scores and len(scores) == len(tokens) else None
    return {
        "pipeline": PIPELINE_VERSION,
        "method": method,
        "seconds": round(time.perf_counter() - start, 3),
        "raw": raw,
        "fields": values,
        "page_confidence": confidence,
        "field_confidence": field_confidence,
    }
