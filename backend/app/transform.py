"""GoldenDict-compatible article and CSS URL transformation."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup

from .text import normalize_resource_key


_CSS_URL = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_IMPORT = re.compile(r"(@import\s+)([\"'])(.*?)\2", re.IGNORECASE)
_REMOTE_SCHEMES = {"http", "https", "data", "blob", "mailto", "tel"}
_LOOKUP_SCHEMES = {"entry", "bword", "gdlookup"}
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


def transform_article_html(html: str, dictionary_id: str) -> str:
    """Return a balanced fragment containing browser-safe resource URLs.

    Dictionary scripts and inline handlers are deliberately retained for
    rendering fidelity. Consumers must render the fragment in an untrusted
    sandbox, as documented by the frontend/backend integration contract.
    """

    soup = BeautifulSoup(html, "html.parser")

    for old, new in {
        "html": "gd-section-html",
        "body": "gd-section-body",
        "head": "gd-section-head",
    }.items():
        for tag in soup.find_all(old):
            tag.name = new

    for tag in soup.find_all(["a", "area"]):
        href = tag.get("href")
        if href:
            _rewrite_anchor(tag, str(href), dictionary_id)

    for tag_name, attribute in (
        ("link", "href"),
        ("script", "src"),
        ("img", "src"),
        ("audio", "src"),
        ("video", "src"),
        ("video", "poster"),
        ("source", "src"),
        ("track", "src"),
        ("embed", "src"),
        ("input", "src"),
        ("object", "data"),
    ):
        for tag in soup.find_all(tag_name):
            value = tag.get(attribute)
            if value:
                tag[attribute] = _rewrite_resource_reference(str(value), dictionary_id)

    for tag in soup.find_all(["img", "source"]):
        if tag.get("srcset"):
            tag["srcset"] = _rewrite_srcset(str(tag["srcset"]), dictionary_id)

    for tag in soup.find_all(style=True):
        tag["style"] = rewrite_css_urls(str(tag["style"]), dictionary_id)

    for tag in soup.find_all("style"):
        if tag.string is not None:
            tag.string.replace_with(rewrite_css_urls(str(tag.string), dictionary_id))

    return "".join(str(node) for node in soup.contents)


def _rewrite_anchor(tag, href: str, dictionary_id: str) -> None:
    value = href.strip()
    if value.startswith("//"):
        tag["href"] = "https:" + value
        return
    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold()
    if scheme in _REMOTE_SCHEMES or value.startswith("#"):
        return
    if scheme in _AUDIO_SCHEMES:
        rewritten = _rewrite_resource_reference(value, dictionary_id)
        tag["href"] = rewritten
        tag["data-gd-audio"] = rewritten
        tag["data-gd-action"] = "audio"
        tag["data-gd-dictionary"] = dictionary_id
        return
    if scheme in _RESOURCE_SCHEMES:
        tag["href"] = _rewrite_resource_reference(value, dictionary_id)
        tag["data-gd-action"] = "resource"
        tag["data-gd-dictionary"] = dictionary_id
        return
    if scheme in _LOOKUP_SCHEMES:
        target = "/".join(part for part in (parsed.netloc, parsed.path.lstrip("/")) if part)
    elif scheme:
        # Preserve explicit custom schemes used by some dictionaries.
        return
    else:
        target = value
    target = unquote(target).strip()
    if not target:
        return
    tag["data-gd-lookup"] = target
    tag["data-gd-action"] = "lookup"
    tag["data-gd-word"] = target
    tag["data-gd-dictionary"] = dictionary_id
    tag["href"] = "#gdlookup=" + quote(target, safe="")


def _rewrite_resource_reference(value: str, dictionary_id: str) -> str:
    stripped = value.strip()
    if stripped.startswith("//"):
        return "https:" + stripped
    if _is_external_or_fragment(stripped):
        return stripped
    try:
        return resource_url(dictionary_id, stripped)
    except ValueError:
        return "about:blank"


def _rewrite_srcset(value: str, dictionary_id: str) -> str:
    rewritten: list[str] = []
    # Data URLs can contain commas, but are already absolute and conventionally
    # appear as the sole candidate. Preserve them without splitting.
    if value.lstrip().casefold().startswith("data:"):
        return value
    for candidate in re.split(r",\s*", value):
        candidate = candidate.strip()
        if not candidate:
            continue
        url_and_descriptor = candidate.split(maxsplit=1)
        url = _rewrite_resource_reference(url_and_descriptor[0], dictionary_id)
        rewritten.append(url if len(url_and_descriptor) == 1 else f"{url} {url_and_descriptor[1]}")
    return ", ".join(rewritten)


def _is_external_or_fragment(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith(("#", "//")):
        return True
    return urlsplit(stripped).scheme.casefold() in _REMOTE_SCHEMES


def decode_css(body: bytes, fallback_encoding: str = "utf-8") -> str:
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
        return body.decode(fallback_encoding or "utf-8", errors="replace")


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
