"""Container health probe that requires a fully published startup catalog."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import urlopen


HEALTH_URL = "http://127.0.0.1:8080/api/v1/health"


def is_ready(payload: Any) -> bool:
    """Return true only for the API's explicit ready/ok health contract."""

    return (
        isinstance(payload, dict)
        and payload.get("ready") is True
        and payload.get("status") == "ok"
    )


def main() -> int:
    try:
        with urlopen(HEALTH_URL, timeout=3) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return 1
    return 0 if is_ready(payload) else 1


if __name__ == "__main__":
    raise SystemExit(main())
