"""Legacy direct development launcher.

Supported host and packaged deployments use ``host_console.py`` or
``app_launcher.py``.  This convenience entry point intentionally listens only
on loopback and must not be used to expose the application to a network.
"""

import uvicorn

from pathlib import Path

from server.database import engine
from server.migration_runner import upgrade_database

if __name__ == "__main__":
    migration = upgrade_database(
        engine,
        base_dir=Path(__file__).resolve().parent,
        adopt_existing=True,
    )
    print(
        f"Database migration: {migration.previous or '<none>'} -> {migration.current}"
    )
    print("Starting So hoa All in One development server on loopback only...")
    print("Please open your browser and navigate to: http://127.0.0.1:8000")
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)
