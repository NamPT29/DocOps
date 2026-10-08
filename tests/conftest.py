"""Cấu hình chung cho test.

Nạp server.main là gắn handler ghi log vào settings.log_dir (mặc định logs/ của repo).
Đặt LOG_DIR sang thư mục tạm TRƯỚC khi test nào import server, rồi xóa khi chạy xong.
"""
import os
import shutil
import tempfile

TEST_LOG_DIR = tempfile.mkdtemp(prefix="docops-test-logs-")
os.environ["LOG_DIR"] = TEST_LOG_DIR


def pytest_sessionfinish(session, exitstatus):
    from server.logging_config import close_managed_logging_handlers

    close_managed_logging_handlers()
    shutil.rmtree(TEST_LOG_DIR, ignore_errors=True)
