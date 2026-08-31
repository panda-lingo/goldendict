"""Unicode and untrusted resource-path normalization."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import unquote


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def normalize_headword(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def display_text(value: bytes | str, encoding: str = "utf-8") -> str:
    if isinstance(value, str):
        return value.strip("\x00")
    return value.decode(encoding, errors="replace").strip("\x00")


def normalize_resource_key(
    value: bytes | str,
    *,
    decode_percent: bool = True,
    fold_case: bool = True,
) -> str:
    """Return a safe, slash-separated dictionary resource key.

    URL decoding happens exactly once. Absolute-looking MDict keys are allowed,
    but dot segments, controls and URI schemes are rejected. Callers may request
    case folding, while the GoldenDict-ng adapter opts out so case-sensitive
    filesystem sidecars retain their exact names.
    """

    text = display_text(value, "utf-8")
    decoded = (unquote(text, errors="strict") if decode_percent else text).replace("\\", "/")
    if _CONTROL.search(decoded):
        raise ValueError("resource path contains control characters")
    decoded = decoded.lstrip("/")
    if ":" in decoded.split("/", 1)[0]:
        raise ValueError("resource path must not contain a URI scheme")
    path = PurePosixPath(decoded)
    if not decoded or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("resource path contains an unsafe segment")
    normalized = "/".join(path.parts)
    return normalized.casefold() if fold_case else normalized
