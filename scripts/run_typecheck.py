from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    pyright_entry = project_root / "node_modules" / "pyright" / "index.js"
    if not pyright_entry.is_file():
        print("Thiếu Pyright. Hãy chạy 'npm install' trước.", file=sys.stderr)
        return 2

    return subprocess.call(
        [
            "node",
            str(pyright_entry),
            "--pythonpath",
            sys.executable,
            "--project",
            str(project_root / "pyrightconfig.json"),
        ],
        cwd=project_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
