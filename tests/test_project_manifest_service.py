import pytest

from server.services.project_manifest_service import (
    ProjectManifestError,
    canonicalize_project_relative_path,
    prepare_project_manifest,
    select_required_project_uploads,
)


def manifest_item(relative_path, marker, size=100):
    return {
        "relative_path": relative_path,
        "size": size,
        "sha256": marker * 64,
        "last_modified": "1787247000000",
    }


def test_folder_level_groups_multiple_pdfs_into_one_report():
    prepared = prepare_project_manifest(
        [
            manifest_item(r"001\report-a\page-1.PDF", "a"),
            manifest_item("001/report-a/page-2.pdf", "b"),
            manifest_item("001/report-b/page-1.pdf", "c"),
        ],
        case_level=1,
        report_mode="folder_level",
        report_level=2,
    )

    assert prepared["total_files"] == 3
    assert prepared["total_cases"] == 1
    assert prepared["total_reports"] == 2
    assert prepared["reports"][0] == {
        "case_key": "001",
        "report_key": "001/report-a",
        "report_name": "report-a",
        "file_count": 2,
    }


def test_pdf_mode_treats_each_pdf_as_one_report():
    prepared = prepare_project_manifest(
        [
            manifest_item("001/report-a.pdf", "a"),
            manifest_item("001/report-b.pdf", "b"),
        ],
        case_level=1,
        report_mode="pdf",
    )

    assert prepared["total_reports"] == 2
    assert {row["report_key"] for row in prepared["reports"]} == {
        "001/report-a.pdf",
        "001/report-b.pdf",
    }


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.pdf",
        "/absolute.pdf",
        "C:/absolute.pdf",
        "001/not-a-pdf.txt",
        "",
    ],
)
def test_manifest_rejects_unsafe_or_non_pdf_paths(relative_path):
    with pytest.raises(ProjectManifestError):
        canonicalize_project_relative_path(relative_path)


def test_duplicate_path_is_idempotent_but_conflicting_content_is_rejected():
    duplicate = manifest_item("001/report.pdf", "a")
    prepared = prepare_project_manifest(
        [duplicate, dict(duplicate)],
        case_level=1,
        report_mode="pdf",
    )
    assert prepared["total_files"] == 1

    with pytest.raises(ProjectManifestError, match="nhiều nội dung"):
        prepare_project_manifest(
            [duplicate, manifest_item("001/REPORT.pdf", "b")],
            case_level=1,
            report_mode="pdf",
        )


def test_manifest_rejects_paths_that_do_not_reach_configured_levels():
    with pytest.raises(ProjectManifestError, match="không đủ 2 cấp"):
        prepare_project_manifest(
            [manifest_item("001/report.pdf", "a")],
            case_level=1,
            report_mode="folder_level",
            report_level=2,
        )


def test_only_new_or_changed_files_are_requested_for_upload():
    prepared = prepare_project_manifest(
        [
            manifest_item("001/old.pdf", "a", size=10),
            manifest_item("001/changed.pdf", "b", size=20),
            manifest_item("001/new.pdf", "c", size=30),
        ],
        case_level=1,
        report_mode="pdf",
    )
    existing = [
        {
            "normalized_relative_path": "001/old.pdf",
            "content_sha256": "a" * 64,
            "byte_size": 10,
            "status": "active",
        },
        {
            "normalized_relative_path": "001/changed.pdf",
            "content_sha256": "d" * 64,
            "byte_size": 20,
            "status": "active",
        },
    ]

    required = select_required_project_uploads(prepared["items"], existing)

    assert [item["normalized_relative_path"] for item in required] == [
        "001/changed.pdf",
        "001/new.pdf",
    ]
