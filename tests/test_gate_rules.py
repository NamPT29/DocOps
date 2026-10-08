"""Luật của cổng kiểm tra (scripts/gate.py): selfcheck JS bị treo không được báo đạt."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

GATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("docops_gate", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("last_line", [
    "Project scan submit self-check: OK",
    "project workspace self-check passed",
    "All tests passed",
    "CSP readiness self-check: static scan ready for browser validation; {}",
])
def test_selfcheck_end_line_accepts_the_success_lines_used_in_the_repo(last_line):
    assert load_gate().selfcheck_reached_end(f"một dòng tiến trình\n{last_line}\n")


@pytest.mark.parametrize("stdout", [
    "",
    "\n   \n",
    "bước 1 xong\nbước 2 đang chạy",
])
def test_selfcheck_end_line_rejects_a_run_that_stopped_silently_or_midway(stdout):
    assert not load_gate().selfcheck_reached_end(stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="cần Node")
def test_a_hanging_node_script_exits_zero_so_the_exit_code_alone_cannot_catch_it(tmp_path):
    script = tmp_path / "hang_selfcheck.js"
    script.write_text(
        "(async () => { await new Promise(() => {}); console.log('Hang self-check: OK'); })();\n",
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)

    assert proc.returncode == 0, "đây là lý do cổng phải kiểm thêm dòng kết thúc"
    assert not load_gate().selfcheck_reached_end(proc.stdout)
