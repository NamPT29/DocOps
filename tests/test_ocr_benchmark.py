from scripts.ocr_benchmark import edit_distance, extract_fields


def test_ocr_noise_and_invalid_calendar_date():
    fields = extract_fields("SỞ TƯ PHÁP  CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
                            "Số: 09 / QĐ-VP  ngày 31 tháng 02 năm 2026\nQUYÉT ĐỊNH\nVề việc tổng kết")
    assert fields == dict(organName="SỞ TƯ PHÁP", code="09/QĐ-VP", issuedDate="",
                          typeName="Quyết định", subject="Về việc tổng kết")
    assert edit_distance("ngày", "ngay") == 1


def test_letter_subject_and_missing_fields():
    fields = extract_fields("V/v gửi tài liệu")
    assert fields == dict(typeName="Công văn", subject="gửi tài liệu", issuedDate="", code="", organName="")
