"""Cổng kiểm tra một lệnh: chạy trước mỗi commit, dán nguyên đầu ra vào báo cáo.

    python scripts/gate.py                      đầy đủ (luật tĩnh + selfcheck JS + toàn bộ pytest);
                                                PHẢI commit trước, cây chưa commit là KHÔNG ĐẠT
    python scripts/gate.py --static             chỉ luật tĩnh (vài giây)
    python scripts/gate.py tests/test_x.py      luật tĩnh + selfcheck JS + pytest chỉ các file/đường dẫn này

Luôn ép DATABASE_URL=sqlite:///:memory: nên không bao giờ chạm database dev.
"""
from __future__ import annotations

import ast
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "DATABASE_URL": "sqlite:///:memory:", "PYTHONIOENCODING": "utf-8"}
FROZEN = ("migrations/schema_0001.py", "scripts/verify_packaging_lock.py")
TKINTER_TESTS = (
    "tests/test_export_process_safety.py",
    "tests/test_packaging_runtime.py",
    "tests/test_server_runtime.py",
)
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, env=ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def tree_status() -> list[str]:
    _, status = run(["git", "status", "--short"])
    return [line for line in status.splitlines() if line.strip()]


def describe_tree(dirty: list[str]) -> str:
    _, head = run(["git", "rev-parse", "--short", "HEAD"])
    suffix = f" + {len(dirty)} file chưa commit (kết quả KHÔNG đại diện cho commit)" if dirty else " (cây sạch)"
    return f"Cổng chạy trên commit {head.strip()}{suffix}"


def check_committed_tree(dirty: list[str]) -> None:
    """Cổng đầy đủ dùng để báo cáo phải chạy SAU khi commit (AGENTS.md)."""
    record(
        "Cây đã commit trước khi chạy cổng đầy đủ",
        not dirty,
        "commit rồi chạy lại: " + ", ".join(line[3:] for line in dirty[:8]) if dirty else "",
    )


def check_tests_leave_no_files(before: list[str]) -> None:
    created = [line[3:] for line in tree_status() if line not in before]
    record("Test không ghi file vào thư mục repo", not created, ", ".join(created[:8]))


def check_frozen_files() -> None:
    code, upstream = run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"])
    base = upstream.strip() if code == 0 else "HEAD"
    _, out = run(["git", "diff", "--name-only", base, "--", *FROZEN])
    changed = [line for line in out.splitlines() if line.strip()]
    record("Tệp đóng băng không đổi", not changed, ", ".join(changed))


def check_empty_migrations() -> None:
    bad = []
    for path in sorted((ROOT / "migrations" / "versions").glob("[0-9]*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
                body = [
                    item for item in node.body
                    if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))
                ]
                if all(isinstance(item, ast.Pass) for item in body):
                    bad.append(path.name)
    record("Migration không rỗng", not bad, ", ".join(bad))


def check_tests_do_not_touch_global_engine() -> None:
    bad = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        uses_global = re.search(r"from server\.database import[^\n]*\bengine\b", source)
        if uses_global and re.search(r"\b(drop_all|create_all)\b", source):
            bad.append(path.name)
    record("Test không dùng engine toàn cục với create_all/drop_all", not bad, ", ".join(bad))


def check_sensitive_data_ignored() -> None:
    ignored_code, _ = run(["git", "check-ignore", "-q", "samples_local/"])
    _, tracked = run(["git", "ls-files", "samples_local"])
    problems = []
    if ignored_code != 0:
        problems.append("samples_local/ chưa có trong .gitignore")
    if tracked.strip():
        problems.append("có file đã bị Git theo dõi trong samples_local/")
    record("Dữ liệu mẫu thật không bị đưa vào Git", not problems, "; ".join(problems))


def check_js_swallow_errors() -> None:
    bad = []
    for path in sorted((ROOT / "tests").glob("*selfcheck*.js")):
        source = path.read_text(encoding="utf-8")
        if ".catch(" in source and "process.exitCode" not in source and "process.exit(1)" not in source:
            bad.append(path.name)
    record("Luật chặn selfcheck nuốt lỗi", not bad, ", ".join(bad))


def check_js_selfcheck_requires() -> None:
    """Selfcheck chạy ở máy sạch: chỉ module có sẵn của Node hoặc file trong repo (không jsdom...)."""
    code, out = run(["node", "-p", "require('module').builtinModules.join(',')"])
    builtins = set(out.strip().split(",")) if code == 0 else set()
    bad = []
    for path in sorted((ROOT / "tests").glob("*selfcheck*.js")):
        source = path.read_text(encoding="utf-8")
        for name in re.findall(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", source):
            if name.startswith((".", "/", "node:")) or name in builtins:
                continue
            bad.append(f"{path.name}: {name}")
    record("Selfcheck JS chỉ dùng module có sẵn của Node", not bad, ", ".join(bad))


def check_html_pages() -> None:
    """Mỗi trang một </html>, không gì sau nó, không nạp trùng script (lỗi dán trùng trang)."""
    bad = []
    for path in sorted((ROOT / "frontend").glob("*.html")):
        if path.name == "temp.html":  # bản nháp cũ, không phục vụ người dùng
            continue
        html = path.read_text(encoding="utf-8")
        if html.count("</html>") != 1 or not html.rstrip().endswith("</html>"):
            bad.append(f"{path.name}: phải có đúng một </html> ở cuối file")
        scripts = [src.split("?")[0] for src in re.findall(r'<script[^>]+src="([^"]+)"', html)]
        duplicates = sorted({src for src in scripts if scripts.count(src) > 1})
        if duplicates:
            bad.append(f"{path.name}: nạp trùng {', '.join(duplicates)}")
    record("Trang HTML không dán trùng, không nạp trùng script", not bad, "; ".join(bad))


SELFCHECK_END_LINE = re.compile(r"\b(ok|passed|ready)\b", re.IGNORECASE)


def selfcheck_reached_end(stdout: str) -> bool:
    """Node thoát với mã 0 khi một lời hứa không bao giờ xong, nên selfcheck bị treo trông như đạt.
    Selfcheck chạy tới cuối luôn in một dòng cuối có OK/passed/ready; im lặng hoặc dừng giữa chừng = hỏng."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return bool(lines) and SELFCHECK_END_LINE.search(lines[-1]) is not None


def check_js_selfchecks() -> None:
    files = sorted(glob.glob(str(ROOT / "tests" / "*selfcheck*.js")))
    failed, unfinished = [], []
    for item in files:
        proc = subprocess.run(
            ["node", item], cwd=ROOT, env=ENV, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            failed.append(Path(item).name)
        elif not selfcheck_reached_end(proc.stdout):
            unfinished.append(Path(item).name)
    record(f"Selfcheck JS ({len(files)} file)", not failed, ", ".join(failed))
    record("Selfcheck JS chạy tới dòng kết thúc (treo thì hỏng)", not unfinished, ", ".join(unfinished))


def check_pytest(targets: list[str]) -> None:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if not targets:
            cmd += [f"--ignore={item}" for item in TKINTER_TESTS]
    code, out = run(cmd + targets)
    lines = out.splitlines()
    summary = next((l for l in reversed(lines) if re.search(r"\d+ (passed|failed|error)", l)), "")
    failures = [l for l in lines if l.startswith(("FAILED", "ERROR"))]
    detail = summary.strip()
    if failures:
        detail += "".join(f"\n      {l[:160]}" for l in failures[:12])
    record("pytest", code == 0, detail)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dirty = tree_status()
    targets = [a for a in argv if not a.startswith("--")]
    full = "--static" not in argv and not targets
    if full:
        check_committed_tree(dirty)
    check_frozen_files()
    check_empty_migrations()
    check_tests_do_not_touch_global_engine()
    check_sensitive_data_ignored()
    check_js_swallow_errors()
    check_js_selfcheck_requires()
    check_html_pages()
    if "--static" not in argv:
        check_js_selfchecks()
        check_pytest(targets)
        check_tests_leave_no_files(dirty)
    print()
    print(describe_tree(dirty))
    for name, ok, detail in results:
        print(f"[{'ĐẠT' if ok else 'LỖI'}] {name}" + (f": {detail}" if detail else ""))
    passed = all(ok for _, ok, _ in results)
    print("\nKẾT QUẢ CỔNG:", "ĐẠT" if passed else "KHÔNG ĐẠT")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
