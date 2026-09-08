from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _python_files(relative_directory: str) -> list[Path]:
    return sorted((PROJECT_ROOT / relative_directory).glob("*.py"))


def test_routers_and_services_do_not_build_database_queries_directly():
    offenders = []
    for relative_directory in ("server/routers", "server/services"):
        for path in _python_files(relative_directory):
            source = path.read_text(encoding="utf-8")
            if ".query(" in source:
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == [], (
        "SQLAlchemy queries must live in server/repositories, found in: "
        + ", ".join(offenders)
    )


def test_repositories_do_not_control_transactions():
    offenders = []
    for path in _python_files("server/repositories"):
        source = path.read_text(encoding="utf-8")
        if ".commit(" in source or ".rollback(" in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == [], (
        "Business workflows must own commit/rollback, found in: "
        + ", ".join(offenders)
    )


def test_repository_package_exposes_domain_boundaries():
    from server.repositories import (
        DictionaryRepository,
        DocumentRepository,
        ReviewRepository,
        ServerFolderRepository,
        SubmissionRepository,
        TemplateRepository,
        UserRepository,
    )

    repository_names = {
        repository.__name__
        for repository in (
            DictionaryRepository,
            DocumentRepository,
            ReviewRepository,
            ServerFolderRepository,
            SubmissionRepository,
            TemplateRepository,
            UserRepository,
        )
    }
    assert repository_names == {
        "DictionaryRepository",
        "DocumentRepository",
        "ReviewRepository",
        "ServerFolderRepository",
        "SubmissionRepository",
        "TemplateRepository",
        "UserRepository",
    }
