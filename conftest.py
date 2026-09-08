"""Test-only compatibility for Codex's Windows filesystem sandbox."""

from itertools import count
import os
from pathlib import Path
import shutil
import uuid

import pytest


if os.environ.get("CODEX_CI") == "1":
    _tmp_counter = count()

    @pytest.fixture(scope="session")
    def _codex_tmp_root():
        root = (
            Path(__file__).resolve().parent
            / "scratch"
            / f"pytest-codex-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        root.mkdir(parents=True, mode=0o777)
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @pytest.fixture
    def tmp_path(_codex_tmp_root):
        path = _codex_tmp_root / f"case-{next(_tmp_counter):04d}"
        path.mkdir(mode=0o777)
        return path
