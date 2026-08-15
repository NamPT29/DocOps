"""Data-access repositories used by the application services and routers."""

from server.repositories.document_repository import DocumentRepository
from server.repositories.dictionary_repository import DictionaryRepository
from server.repositories.lookup_repository import LookupRepository
from server.repositories.review_repository import ReviewRepository
from server.repositories.server_folder_repository import ServerFolderRepository
from server.repositories.submission_repository import SubmissionRepository
from server.repositories.task_repository import TaskRepository
from server.repositories.template_repository import TemplateRepository
from server.repositories.user_repository import UserRepository
from server.repositories.submission_view_repository import SubmissionViewRepository

__all__ = [
    "DocumentRepository",
    "DictionaryRepository",
    "LookupRepository",
    "ReviewRepository",
    "ServerFolderRepository",
    "SubmissionRepository",
    "TaskRepository",
    "TemplateRepository",
    "UserRepository",
    'SubmissionViewRepository',
]
