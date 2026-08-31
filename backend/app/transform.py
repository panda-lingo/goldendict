"""GoldenDict-compatible article and CSS URL transformation."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from .text import normalize_resource_key


_CSS_URL = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_IMPORT = re.compile(r"(@import\s+)([\"'])(.*?)\2", re.IGNORECASE)
_REMOTE_SCHEMES = {"http", "https", "data", "blob", "mailto", "tel"}
_AUDIO_SCHEMES = {"sound", "audio", "gdau"}
_RESOURCE_SCHEMES = {"bres", "gdvideo"}
_SCOPED_RESOURCE_SCHEMES = {"bres", "gdau", "gdvideo"}


def resource_base_url(dictionary_id: str) -> str:
    return f"/api/v1/dictionaries/{dictionary_id}/resources/"


def resource_url(
    dictionary_id: str,
    value: str,
    *,
    relative_to: str = "",
    fold_case: bool = True,
) -> str:
    parsed = urlsplit(value.strip().strip("\"'"))
    scheme = parsed.scheme.casefold()
    target_dictionary_id = (
        parsed.netloc
        if scheme in _SCOPED_RESOURCE_SCHEMES and parsed.netloc
        else dictionary_id
    )
    key = _resource_key_from_url(
        value,
        relative_to=relative_to,
        fold_case=fold_case,
    )
    return resource_base_url(target_dictionary_id) + quote(key, safe="/")


def _resource_key_from_url(
    value: str,
    *,
    relative_to: str = "",
    fold_case: bool = True,
) -> str:
    raw = value.strip().strip("\"'")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.casefold()
    if scheme in _SCOPED_RESOURCE_SCHEMES:
        raw = parsed.path.lstrip("/")
    elif scheme in _AUDIO_SCHEMES | _RESOURCE_SCHEMES:
        raw = "/".join(part for part in (parsed.netloc, parsed.path.lstrip("/")) if part)
    else:
        raw = parsed.path
    raw = unquote(raw, errors="strict").replace("\\", "/")
    if relative_to and scheme not in _SCOPED_RESOURCE_SCHEMES and not raw.startswith("/"):
        parent = PurePosixPath(relative_to.replace("\\", "/")).parent
        parts = [part for part in parent.parts if part not in {"", ".", "/"}]
        for part in raw.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    raise ValueError("resource path escapes the dictionary root")
                parts.pop()
            else:
                parts.append(part)
        raw = "/".join(parts)
    return normalize_resource_key(
        raw,
        decode_percent=False,
        fold_case=fold_case,
    )


def rewrite_css_urls(
    css: str,
    dictionary_id: str,
    *,
    resource_path: str = "",
    fold_case: bool = True,
) -> str:
    """Rewrite relative/MDD CSS references to the public resource endpoint."""

    def replace_url(match: re.Match[str]) -> str:
        quote_char, value = match.group(1), match.group(2).strip()
        if _is_external_or_fragment(value):
            if value.startswith("//"):
                value = "https:" + value
            return f"url({quote_char}{value}{quote_char})"
        try:
            rewritten = resource_url(
                dictionary_id,
                value,
                relative_to=resource_path,
                fold_case=fold_case,
            )
        except ValueError:
            return "url(\"about:blank\")"
        return f'url("{rewritten}")'

    def replace_import(match: re.Match[str]) -> str:
        value = match.group(3).strip()
        if _is_external_or_fragment(value):
            if value.startswith("//"):
                value = "https:" + value
            return f"{match.group(1)}{match.group(2)}{value}{match.group(2)}"
        try:
            rewritten = resource_url(
                dictionary_id,
                value,
                relative_to=resource_path,
                fold_case=fold_case,
            )
        except ValueError:
            rewritten = "about:blank"
        return f"{match.group(1)}{match.group(2)}{rewritten}{match.group(2)}"

    return _CSS_IMPORT.sub(replace_import, _CSS_URL.sub(replace_url, css))


def _is_external_or_fragment(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith(("#", "//")):
        return True
    return urlsplit(stripped).scheme.casefold() in _REMOTE_SCHEMES


def decode_css(body: bytes, default_encoding: str = "utf-8") -> str:
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if body.startswith(bom):
            return body.decode(encoding, errors="replace")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode(default_encoding or "utf-8", errors="replace")


def media_type_for(path: str) -> str:
    overrides = {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".oga": "audio/ogg",
        ".ogv": "video/ogg",
    }
    suffix = PurePosixPath(path).suffix.casefold()
    return overrides.get(suffix) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest() + '"'
