from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    pyright_entry = project_root / "node_modules" / "pyright" / "index.js"
    if not pyright_entry.is_file():
        print("Thiếu Pyright. Hãy chạy 'npm install' trước.", file=sys.stderr)
        return 2

    config_path = project_root / "pyrightconfig.json"
    temporary_config = None
    if os.environ.get("CODEX_CI") == "1":
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for key in ("include", "exclude", "ignore"):
            config[key] = [(Path("..") / path).as_posix() for path in config.get(key, [])]
        config["extraPaths"] = ["..", *site.getsitepackages()]
        scratch = project_root / "scratch"
        scratch.mkdir(exist_ok=True)
        temporary_config = scratch / f"pyrightconfig-codex-{os.getpid()}.json"
        temporary_config.write_text(json.dumps(config), encoding="utf-8")
        config_path = temporary_config

    try:
        return subprocess.call(
            [
                "node",
                str(pyright_entry),
                "--pythonpath",
                sys.executable,
                "--project",
                str(config_path),
            ],
            cwd=project_root,
        )
    finally:
        if temporary_config is not None:
            temporary_config.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
