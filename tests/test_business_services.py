from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from server.models import User
from server.routers import auth, processing
from server.services.address_service import normalize_str, process_address
from server.services.server_folder_service import (
    ServerSourceDocument,
    folder_group_for_level,
    source_document_upload_id,
)
from server.services.upload_service import save_validated_upload


@pytest.fixture(autouse=True)
def clear_processing_cache():
    processing.MAPPING_CACHE.clear()
    yield
    processing.MAPPING_CACHE.clear()


def test_address_normalization_keeps_vietnamese_letters_and_removes_separators():
    assert normalize_str("  Phường Cẩm Phả, Quảng Ninh!  ") == (
        "phườngcẩmphảquảngninh"
    )


def test_address_processing_uses_longest_suffix_and_preserves_original_prefix():
    mappings = {
        "mapping_3_cap": {
            "phườngcẩmthànhphốcẩmphảtỉnhquảngninh": {
                "formatted": "Phường Cẩm, Thành phố Cẩm Phả, Tỉnh Quảng Ninh",
                "code": "3-cap",
            }
        },
        "mapping_2_cap": {
            "thànhphốcẩmphảtỉnhquảngninh": {
                "formatted": "Thành phố Cẩm Phả, Tỉnh Quảng Ninh",
                "code": "2-cap",
            }
        },
    }

    result = process_address(
        "Tổ 7, Phường Cẩm, Thành phố Cẩm Phả, Tỉnh Quảng Ninh",
        "col_20",
        mappings,
    )

    assert result == {
        "formatted": "Tổ 7, Phường Cẩm, Thành phố Cẩm Phả, Tỉnh Quảng Ninh",
        "code": "3-cap",
    }


@pytest.mark.parametrize("value", ["", "   ", "Địa chỉ không có trong danh mục"])
def test_address_processing_returns_empty_result_when_no_address_matches(value):
    assert process_address(value, "col_20", {"mapping_3_cap": {}}) == {}


def test_measurement_address_adds_exact_unit_metadata():
    mappings = {
        "mapping_3_cap": {
            "phườnghồnghàthànhphốhạlongtỉnhquảngninh": {
                "formatted": "Phường Hồng Hà, Thành phố Hạ Long, Tỉnh Quảng Ninh",
                "code": "HH",
            }
        }
    }
    unit_key = normalize_str("Phường Hồng Hà, Thành phố Hạ Long")

    result = process_address(
        "Phường Hồng Hà, Thành phố Hạ Long, Tỉnh Quảng Ninh",
        "col_92",
        mappings,
        {
            unit_key: {
                "don_vi": "Đội đo đạc số 1",
                "ngay_hoan_thanh": "14/08/2026",
            }
        },
    )

    assert result["don_vi_do"] == "Đội đo đạc số 1"
    assert result["ngay_hoan_thanh"] == "14/08/2026"


def test_measurement_address_falls_back_to_ward_prefix():
    mappings = {
        "mapping_2_cap": {
            "phườnghồnghàthànhphốhạlongtỉnhquảngninh": {
                "formatted": "Phường Hồng Hà, Thành phố Hạ Long, Tỉnh Quảng Ninh",
                "code": "HH",
            }
        }
    }

    result = process_address(
        "Phường Hồng Hà, Thành phố Hạ Long, Tỉnh Quảng Ninh",
        "col_92",
        mappings,
        {
            normalize_str("Phường Hồng Hà mở rộng"): {
                "don_vi": "Đội dự phòng",
                "ngay_hoan_thanh": "15/08/2026",
            }
        },
    )

    assert result["don_vi_do"] == "Đội dự phòng"
    assert result["ngay_hoan_thanh"] == "15/08/2026"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("report.pdf", b"%PDF-1.7\nbody"),
        ("scan.png", b"\x89PNG\r\n\x1a\nbody"),
        ("photo.jpg", b"\xff\xd8\xffbody"),
        ("photo.jpeg", b"\xff\xd8\xffbody"),
        ("scan.webp", b"RIFF\x04\x00\x00\x00WEBPbody"),
    ],
)
def test_valid_document_upload_is_saved_atomically(tmp_path, filename, content):
    destination = tmp_path / filename
    upload = UploadFile(filename=f"../{filename}", file=BytesIO(content))

    original_name = save_validated_upload(
        upload,
        str(destination),
        kind="document",
    )

    assert original_name == filename
    assert destination.read_bytes() == content
    assert list(tmp_path.glob("*.part")) == []


def test_upload_rejects_unsupported_extension_without_creating_file(tmp_path):
    destination = tmp_path / "payload.exe"
    upload = UploadFile(filename="payload.exe", file=BytesIO(b"MZ"))

    with pytest.raises(HTTPException) as error:
        save_validated_upload(upload, str(destination), kind="document")

    assert error.value.status_code == 400
    assert not destination.exists()


@pytest.mark.parametrize(
    ("filename", "content"),
    [("empty.pdf", b""), ("fake.pdf", b"not-a-pdf")],
)
def test_upload_rejects_empty_or_mismatched_document_and_cleans_staging_file(
    tmp_path,
    filename,
    content,
):
    destination = tmp_path / filename
    upload = UploadFile(filename=filename, file=BytesIO(content))

    with pytest.raises(HTTPException) as error:
        save_validated_upload(upload, str(destination), kind="document")

    assert error.value.status_code == 400
    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_oversized_upload_preserves_existing_destination_and_cleans_staging(tmp_path):
    destination = tmp_path / "report.pdf"
    destination.write_bytes(b"existing-content")
    upload = UploadFile(filename="report.pdf", file=BytesIO(b"%PDF-too-large"))

    with pytest.raises(HTTPException) as error:
        save_validated_upload(
            upload,
            str(destination),
            kind="document",
            max_bytes=5,
        )

    assert error.value.status_code == 413
    assert destination.read_bytes() == b"existing-content"
    assert list(tmp_path.glob("*.part")) == []


def _excel_bytes() -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
    return stream.getvalue()


def test_excel_upload_requires_a_valid_office_zip(tmp_path):
    valid_destination = tmp_path / "valid.xlsx"
    valid_content = _excel_bytes()

    save_validated_upload(
        UploadFile(filename="valid.xlsx", file=BytesIO(valid_content)),
        str(valid_destination),
        kind="excel",
    )

    assert valid_destination.read_bytes() == valid_content

    invalid_destination = tmp_path / "invalid.xlsx"
    with pytest.raises(HTTPException) as error:
        save_validated_upload(
            UploadFile(filename="invalid.xlsx", file=BytesIO(b"PK-not-a-zip")),
            str(invalid_destination),
            kind="excel",
        )

    assert error.value.status_code == 400
    assert not invalid_destination.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_upload_has_no_default_size_limit(tmp_path):
    destination = tmp_path / "large-report.pdf"
    content = b"%PDF-1.7\n" + (b"x" * (25 * 1024 * 1024))

    save_validated_upload(
        UploadFile(filename="large-report.pdf", file=BytesIO(content)),
        str(destination),
        kind="document",
    )

    assert destination.stat().st_size == len(content)
    assert list(tmp_path.glob("*.part")) == []


def _source_document(path: Path, *, parts=("004", "0011")) -> ServerSourceDocument:
    return ServerSourceDocument(
        source_path=path,
        relative_path="00000000/004/0011/report.pdf",
        grouping_prefix=("00000000",),
        grouping_parts=parts,
    )


def test_folder_grouping_honors_selected_depth_and_root_sentinel(tmp_path):
    document = _source_document(tmp_path / "report.pdf")

    assert folder_group_for_level(document, 1) == "00000000/004"
    assert folder_group_for_level(document, 2) == "00000000/004/0011"
    assert folder_group_for_level(document, 99) == "00000000/004/0011"

    root_document = ServerSourceDocument(
        source_path=tmp_path / "root.pdf",
        relative_path="root.pdf",
        grouping_prefix=(),
        grouping_parts=(),
    )
    assert folder_group_for_level(root_document, 1) == "__ROOT__"

    with pytest.raises(HTTPException) as error:
        folder_group_for_level(document, 0)
    assert error.value.status_code == 400


def test_source_document_id_is_stable_and_tracks_file_or_template_changes(tmp_path):
    source_path = tmp_path / "report.pdf"
    source_path.write_bytes(b"%PDF-first")
    document = _source_document(source_path)

    original_id = source_document_upload_id(document, template_id=1)

    assert source_document_upload_id(document, template_id=1) == original_id
    assert source_document_upload_id(document, template_id=2) != original_id

    source_path.write_bytes(b"%PDF-second-version")
    changed_file_id = source_document_upload_id(document, template_id=1)
    assert changed_file_id != original_id


def test_mapping_cache_reads_excel_once_and_reloads_after_invalidation(mocker):
    repository_class = mocker.patch.object(processing, "TemplateRepository")
    repository_class.return_value.get.return_value = SimpleNamespace(filename="form.xlsx")
    mocker.patch.object(processing.os.path, "exists", return_value=True)
    ma_xa_loader = mocker.patch.object(
        processing,
        "get_ma_xa_mapping",
        return_value={"mapping_3_cap": {}},
    )
    unit_loader = mocker.patch.object(
        processing,
        "get_don_vi_do_mapping",
        return_value={"ward": {}},
    )

    first = processing.get_mappings(7, db=object())
    second = processing.get_mappings(7, db=object())

    assert second is first
    assert ma_xa_loader.call_count == 1
    assert unit_loader.call_count == 1

    processing.invalidate_mappings(7)
    processing.get_mappings(7, db=object())

    assert ma_xa_loader.call_count == 2
    assert unit_loader.call_count == 2


@pytest.mark.parametrize(
    ("template", "file_exists", "expected_detail"),
    [
        (None, True, "Template not found"),
        (SimpleNamespace(filename="missing.xlsx"), False, "Template file not found"),
    ],
)
def test_mapping_loader_returns_not_found_for_missing_dependencies(
    mocker,
    template,
    file_exists,
    expected_detail,
):
    repository_class = mocker.patch.object(processing, "TemplateRepository")
    repository_class.return_value.get.return_value = template
    mocker.patch.object(processing.os.path, "exists", return_value=file_exists)

    with pytest.raises(HTTPException) as error:
        processing.get_mappings(9, db=object())

    assert error.value.status_code == 404
    assert error.value.detail == expected_detail


def test_field_processing_dispatches_only_supported_address_columns(mocker):
    mappings = {"ma_xa": {"mapping_3_cap": {}}, "don_vi": {}}
    mocker.patch.object(processing, "get_mappings", return_value=mappings)
    address_processor = mocker.patch.object(
        processing,
        "process_address",
        return_value={"formatted": "Địa chỉ chuẩn", "code": "01"},
    )

    supported = processing.api_process_field(
        3,
        processing.ProcessFieldRequest(field_name="col_92", value="địa chỉ"),
        current_user={"id": 1},
        db=object(),
    )
    unsupported = processing.api_process_field(
        3,
        processing.ProcessFieldRequest(field_name="col_8", value="hồ sơ"),
        current_user={"id": 1},
        db=object(),
    )

    assert supported == {
        "status": "ok",
        "data": {"formatted": "Địa chỉ chuẩn", "code": "01"},
    }
    assert unsupported == {"status": "ok", "data": {}}
    address_processor.assert_called_once_with(
        val="địa chỉ",
        field_name="col_92",
        ma_xa_mapping=mappings["ma_xa"],
        don_vi_do_mapping=mappings["don_vi"],
    )


def test_password_hashes_are_salted_and_malformed_hashes_fail_closed():
    first = auth.hash_password("strong-password")
    second = auth.hash_password("strong-password")

    assert first != second
    assert auth.verify_password("strong-password", first)
    assert not auth.verify_password("wrong-password", first)
    assert not auth.verify_password("strong-password", "scrypt$broken")
    assert not auth.verify_password("strong-password", None)
    with pytest.raises(ValueError):
        auth.hash_password("")


@pytest.mark.parametrize(
    ("role", "can_input", "can_review", "expected"),
    [
        (
            "admin",
            False,
            False,
            {
                "can_input": True,
                "can_review": True,
                "roles": ["admin", "input", "reviewer"],
            },
        ),
        (
            "user",
            True,
            True,
            {
                "can_input": True,
                "can_review": True,
                "roles": ["input", "reviewer"],
            },
        ),
        (
            "user",
            False,
            False,
            {"can_input": False, "can_review": False, "roles": []},
        ),
    ],
)
def test_capability_profile_matches_work_assigned_to_user(
    role,
    can_input,
    can_review,
    expected,
):
    user = User(username="tester", password="hash", role=role)
    assert auth._capability_profile(
        user,
        can_input=can_input,
        can_review=can_review,
    ) == expected
