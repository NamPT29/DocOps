"""Run versioned database migrations outside the FastAPI import path."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.database import engine
from server.migration_runner import upgrade_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help=(
            "Validate an existing pre-Alembic schema, stamp revision 0001, "
            "then upgrade to head. Back up the database first."
        ),
    )
    args = parser.parse_args()
    result = upgrade_database(
        engine,
        base_dir=ROOT,
        adopt_existing=args.adopt_existing,
    )
    action = "adopted" if result.adopted_existing else "upgraded"
    print(
        f"Database {action}: {result.previous or '<none>'} -> {result.current}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
