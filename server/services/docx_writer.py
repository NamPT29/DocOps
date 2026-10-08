"""Ghi file Word (.docx) tối giản: đoạn văn và bảng, phông Times New Roman, khổ A4.

Không cần thư viện ngoài: .docx là file zip gồm vài tệp XML (chuẩn Office Open XML).
"""
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)
_FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'


def _run(text: str, *, bold=False, italic=False, size=13) -> str:
    properties = _FONT + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + f'<w:sz w:val="{size * 2}"/>'
    parts = str(text).split("\n")
    body = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(part)}</w:t>' for part in parts)
    return f"<w:r><w:rPr>{properties}</w:rPr>{body}</w:r>"


def paragraph(text: str = "", *, bold=False, italic=False, size=13, align="left", space_after=6) -> str:
    justification = {"left": "left", "center": "center", "right": "right", "both": "both"}[align]
    return (
        f'<w:p><w:pPr><w:spacing w:after="{space_after * 20}"/><w:jc w:val="{justification}"/></w:pPr>'
        f"{_run(text, bold=bold, italic=italic, size=size) if text else ''}</w:p>"
    )


def _cell(text, width: int, *, bold=False, align="left", size=12) -> str:
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
        f"{paragraph('' if text is None else str(text), bold=bold, align=align, size=size, space_after=0)}</w:tc>"
    )


def table(header: list[str], rows: list[list], widths: list[int], *, borders=True, size=12) -> str:
    """Bảng; widths tính theo 1/20 point (dxa), tổng khoảng 9600 cho khổ A4 lề 2 cm."""
    border = (
        "<w:tblBorders>" + "".join(
            f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
            for side in ("top", "left", "bottom", "right", "insideH", "insideV")
        ) + "</w:tblBorders>"
    ) if borders else ""
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    head = (
        "<w:tr>" + "".join(_cell(text, width, bold=True, align="center", size=size) for text, width in zip(header, widths)) + "</w:tr>"
        if header else ""
    )
    body = "".join(
        "<w:tr>" + "".join(_cell(value, width, size=size) for value, width in zip(row, widths)) + "</w:tr>"
        for row in rows
    )
    return f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>{border}</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{head}{body}</w:tbl>'


def build_docx(blocks: list[str]) -> bytes:
    """blocks: chuỗi XML do paragraph()/table() tạo. Khổ A4, lề trái 3 cm, các lề khác 2 cm."""
    section = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>'
        + "".join(blocks) + section + "</w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()
