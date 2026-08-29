"""Verify that the active Python environment matches the packaging lock."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lock_file", type=Path)
    args = parser.parse_args()

    failures: list[str] = []
    for raw_line in args.lock_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            failures.append(f"missing: {requirement.name}")
            continue
        if requirement.specifier and not requirement.specifier.contains(
            installed, prereleases=True
        ):
            failures.append(
                f"version mismatch: {requirement.name} {installed} not in "
                f"{requirement.specifier}"
            )

    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("Packaging environment matches requirements-package.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
