"""Test không được ghi log vào logs/ của repo (lát E2).

logs/ nằm trong .gitignore nên luật "Test không ghi file vào thư mục repo" của cổng không thấy;
test này kiểm trực tiếp nơi server ghi log khi chạy dưới pytest.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

LIST_LOG_FILES = (
    "import json, logging, server.main; "
    "print(json.dumps([h.baseFilename for h in logging.getLogger().handlers if hasattr(h, 'baseFilename')]))"
)


def _inside_repo(path) -> bool:
    return Path(path).resolve().is_relative_to(REPO)


def test_settings_log_dir_is_outside_repo():
    from server.settings import settings

    assert not _inside_repo(settings.log_dir), settings.log_dir


def test_server_log_files_are_outside_repo():
    # Tiến trình riêng: test khác có thể đã gỡ handler log trong tiến trình pytest này.
    result = subprocess.run(
        [sys.executable, "-c", LIST_LOG_FILES],
        cwd=REPO, env=dict(os.environ), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    files = json.loads(result.stdout.strip().splitlines()[-1])
    assert files, "server phải gắn handler ghi file log"
    assert [path for path in files if _inside_repo(path)] == []
