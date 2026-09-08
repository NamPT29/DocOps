"""Release identity shared by the API and Windows packaging pipeline."""

from __future__ import annotations


APP_NAME = "Scan To Excel Host"
APP_VERSION = "0.2"
SUPPORTED_POSTGRESQL_MAJOR = 18
DEFAULT_PUBLIC_HOSTNAME = "nhaplieu1.aivn.net.vn"


def release_payload() -> dict[str, str | int]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "postgresql_major": SUPPORTED_POSTGRESQL_MAJOR,
        "public_hostname": DEFAULT_PUBLIC_HOSTNAME,
    }
