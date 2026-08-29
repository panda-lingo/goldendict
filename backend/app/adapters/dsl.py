"""ABBYY Lingvo DSL reader.

The parser deliberately keeps the on-disk format and GoldenDict-compatible
HTML conversion in this module.  The tag/class mapping follows
``goldendict-ng/src/dict/dsl.cc`` so future upstream compatibility updates have
one obvious place to land.
"""

from __future__ import annotations

import bisect
import gzip
import html
import io
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TextIO
from urllib.parse import quote, unquote, urlsplit

from ..text import normalize_headword
from ..transform import (
    decode_css,
    etag_for,
    media_type_for,
    rewrite_css_urls,
    transform_article_html,
)
from .base import (
    MAX_SUGGESTION_LIMIT,
    DictionaryAdapter,
    DictionaryArticle,
    DictionaryMetadata,
    DictionaryResource,
    UnsupportedDictionaryFormat,
    stable_dictionary_id,
)


_HEADER_RE = re.compile(r"^#([A-Za-z_]+)\s+(.*?)\s*$")
_COLOR_RE = re.compile(r"(?:#[0-9a-fA-F]{3,8}|[A-Za-z]{1,32})\Z")
_MARGIN_TAG_RE = re.compile(r"m[0-9]?\Z")
_MAX_DSL_LINE_CHARS = 4 * 1024 * 1024
_MAX_ARTICLE_CHARS = 32 * 1024 * 1024
_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mid",
    ".midi",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


class DSLReadError(RuntimeError):
    """Raised when a loaded DSL bundle cannot be read safely."""


@dataclass(frozen=True, slots=True)
class _DslRecord:
    headwords: tuple[str, ...]
    body_offset: int


@dataclass(frozen=True, slots=True)
class _DslMatch:
    record: _DslRecord
    display_headword: str


@dataclass(slots=True)
class _DslText:
    value: str


@dataclass(slots=True)
class _DslLiteral:
    value: str


@dataclass(slots=True)
class _DslTag:
    name: str
    argument: str
    children: list["_DslNode"] = field(default_factory=list)


_DslNode = _DslText | _DslLiteral | _DslTag


class DSLAdapter(DictionaryAdapter):
    """A thread-safe, lazily-reading adapter for ``.dsl`` and ``.dsl.dz``."""

    format_name = "dsl"

    def __init__(
        self,
        path: str | Path,
        dictionary_id: str | None = None,
        *,
        name: str | None = None,
        max_resource_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        if not self.supports(self._path):
            raise UnsupportedDictionaryFormat(
                f"expected a .dsl or .dsl.dz file: {self._path}"
            )
        if not self._path.is_file():
            raise FileNotFoundError(self._path)

        self._encoding = self._detect_encoding()
        headers, index, display_words = self._build_index()
        self._index = index
        ordered = sorted(display_words.items(), key=lambda item: (item[0], item[1]))
        self._suggestion_keys = tuple(item[0] for item in ordered)
        self._suggestion_words = tuple(item[1] for item in ordered)
        self._resource_roots = self._find_resource_roots()
        self._max_resource_bytes = max(0, max_resource_bytes)

        resolved_id = dictionary_id or stable_dictionary_id(self.format_name, self._path)
        self._dictionary_id = resolved_id
        fallback_name = self._dictionary_stem()
        self.metadata = DictionaryMetadata(
            dictionary_id=resolved_id,
            name=name or headers.get("NAME") or fallback_name,
            format=self.format_name,
            word_count=len(display_words),
            main_path=self._path,
            source_language=headers.get("INDEX_LANGUAGE"),
            target_language=headers.get("CONTENTS_LANGUAGE"),
        )

    @classmethod
    def supports(cls, path: str | Path) -> bool:
        lowered = str(path).casefold()
        return lowered.endswith(".dsl") or lowered.endswith(".dsl.dz")

    def lookup(self, word: str) -> DictionaryArticle | None:
        key = _lookup_key(word)
        if not key:
            return None
        matches = self._index.get(key)
        if not matches:
            return None

        rendered: list[str] = []
        seen_offsets: set[int] = set()
        with self._open_text() as source:
            for match in matches:
                if match.record.body_offset in seen_offsets:
                    continue
                seen_offsets.add(match.record.body_offset)
                body = self._read_body(source, match.record.body_offset)
                definition = _render_dsl(
                    body,
                    match.display_headword,
                    self._dictionary_id,
                )
                shown_headwords = ", ".join(match.record.headwords)
                rendered.append(
                    '<div class="dsl_article">'
                    '<div class="dsl_headwords"><p>'
                    f"{html.escape(shown_headwords)}"
                    "</p></div>"
                    f'<div class="dsl_definition">{definition}</div>'
                    "</div>"
                )
        transformed = transform_article_html("".join(rendered), self._dictionary_id)
        return DictionaryArticle(html=transformed, headword=matches[0].display_headword)

    def suggestions(self, prefix: str, limit: int) -> list[str]:
        bounded_limit = min(max(int(limit), 0), MAX_SUGGESTION_LIMIT)
        if bounded_limit == 0:
            return []
        folded_prefix = _lookup_key(prefix)
        if not folded_prefix:
            return []
        position = bisect.bisect_left(self._suggestion_keys, folded_prefix)
        result: list[str] = []
        while position < len(self._suggestion_keys) and len(result) < bounded_limit:
            key = self._suggestion_keys[position]
            if not key.startswith(folded_prefix):
                break
            result.append(self._suggestion_words[position])
            position += 1
        return result

    def resource(self, resource_path: str) -> DictionaryResource | None:
        parts = _safe_resource_parts(resource_path)
        if parts is None:
            return None
        for root in self._resource_roots:
            candidate = _contained_file(root, parts)
            if candidate is None:
                continue
            if candidate.stat().st_size > self._max_resource_bytes:
                raise DSLReadError("dictionary resource exceeds the configured size limit")
            body = candidate.read_bytes()
            if len(body) > self._max_resource_bytes:
                raise DSLReadError("dictionary resource exceeds the configured size limit")
            media_type = media_type_for("/".join(parts))
            if media_type.startswith("text/css"):
                css = decode_css(body)
                body = rewrite_css_urls(
                    css,
                    self._dictionary_id,
                    resource_path="/".join(parts),
                ).encode("utf-8")
            return DictionaryResource(
                body=body,
                media_type=media_type,
                etag=etag_for(body),
            )
        return None

    def _dictionary_stem(self) -> str:
        name = self._path.name
        lowered = name.casefold()
        if lowered.endswith(".dsl.dz"):
            return name[:-7]
        return name[:-4]

    def _open_binary(self) -> BinaryIO:
        if str(self._path).casefold().endswith(".dz"):
            return gzip.open(self._path, "rb")
        return self._path.open("rb")

    def _detect_encoding(self) -> str:
        with self._open_binary() as source:
            prefix = source.read(4)
        if prefix.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "utf-16"
        return "utf-8"

    def _open_text(self) -> TextIO:
        return io.TextIOWrapper(
            self._open_binary(),
            encoding=self._encoding,
            errors="strict",
            newline=None,
        )

    def _build_index(
        self,
    ) -> tuple[dict[str, str], dict[str, tuple[_DslMatch, ...]], dict[str, str]]:
        headers: dict[str, str] = {}
        mutable_index: dict[str, list[_DslMatch]] = {}
        display_words: dict[str, str] = {}
        pending_headwords: list[str] = []
        in_body = False

        with self._open_text() as source:
            while True:
                offset = source.tell()
                line = source.readline(_MAX_DSL_LINE_CHARS + 1)
                if line == "":
                    break
                if len(line) > _MAX_DSL_LINE_CHARS:
                    raise UnsupportedDictionaryFormat("DSL line exceeds the safety limit")
                content = line.rstrip("\r\n")
                if content.startswith((" ", "\t")):
                    if pending_headwords:
                        record = _DslRecord(tuple(pending_headwords), offset)
                        for display_headword in pending_headwords:
                            key = _lookup_key(display_headword)
                            if not key:
                                continue
                            refs = mutable_index.setdefault(key, [])
                            if all(ref.record.body_offset != offset for ref in refs):
                                refs.append(_DslMatch(record, display_headword))
                            display_words.setdefault(key, display_headword)
                        pending_headwords = []
                    in_body = True
                    continue

                if not content.strip():
                    in_body = False
                    pending_headwords = []
                    continue

                header_match = _HEADER_RE.match(content)
                if header_match and not mutable_index and not in_body:
                    headers[header_match.group(1).upper()] = _unquote(
                        header_match.group(2)
                    )
                    continue

                headword = _plain_headword(content)
                if not headword:
                    continue
                if in_body:
                    pending_headwords = [headword]
                    in_body = False
                else:
                    pending_headwords.append(headword)

        return (
            headers,
            {key: tuple(refs) for key, refs in mutable_index.items()},
            display_words,
        )

    @staticmethod
    def _read_body(source: TextIO, offset: int) -> str:
        source.seek(offset)
        lines: list[str] = []
        total_chars = 0
        while True:
            line = source.readline(_MAX_DSL_LINE_CHARS + 1)
            if line == "":
                break
            if len(line) > _MAX_DSL_LINE_CHARS:
                raise DSLReadError("DSL line exceeds the safety limit")
            content = line.rstrip("\r\n")
            if not content.startswith((" ", "\t")):
                break
            definition_line = content.lstrip(" \t")
            total_chars += len(definition_line)
            if total_chars > _MAX_ARTICLE_CHARS:
                raise DSLReadError("DSL article exceeds the safety limit")
            lines.append(definition_line)
        return "\n".join(lines)

    def _find_resource_roots(self) -> tuple[Path, ...]:
        path_text = str(self._path)
        dictionary_directory = self._path.parent.resolve()
        candidates = [
            Path(path_text + ".files"),
            self._path.with_suffix(".files"),
        ]
        lowered = path_text.casefold()
        if lowered.endswith(".dsl.dz"):
            candidates.extend(
                (
                    Path(path_text[:-3] + ".files"),
                    Path(path_text[:-7] + ".files"),
                )
            )
        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            try:
                resolved.relative_to(dictionary_directory)
            except ValueError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            unique.append(resolved)
        return tuple(unique)


# Common spelling used by Python class-name conventions and prospective factory
# integrations.  Keep both without duplicating implementation.
DslAdapter = DSLAdapter


def _lookup_key(value: str) -> str:
    return normalize_headword(value)


def _unquote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        stripped = stripped[1:-1]
    result: list[str] = []
    escaped = False
    for character in stripped:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            result.append(character)
    if escaped:
        result.append("\\")
    return "".join(result)


def _plain_headword(value: str) -> str:
    """Drop DSL markup while preserving escaped literal brackets."""

    result: list[str] = []
    position = 0
    while position < len(value):
        character = value[position]
        if character == "\\" and position + 1 < len(value):
            result.append(value[position + 1])
            position += 2
            continue
        if character == "[":
            closing = _find_unescaped_closing_bracket(value, position + 1)
            if closing is not None:
                position = closing + 1
                continue
        result.append(character)
        position += 1
    return "".join(result).strip()


def _find_unescaped_closing_bracket(value: str, start: int) -> int | None:
    escaped = False
    for position in range(start, len(value)):
        character = value[position]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "]":
            return position
    return None


def _parse_dsl_nodes(value: str) -> list[_DslNode]:
    root: list[_DslNode] = []
    stack: list[tuple[str, list[_DslNode]]] = [("", root)]
    text_buffer: list[str] = []

    def flush_text() -> None:
        if text_buffer:
            stack[-1][1].append(_DslText("".join(text_buffer)))
            text_buffer.clear()

    position = 0
    while position < len(value):
        character = value[position]
        if character == "\\" and position + 1 < len(value):
            flush_text()
            stack[-1][1].append(_DslLiteral(value[position + 1]))
            position += 2
            continue
        if character != "[":
            text_buffer.append(character)
            position += 1
            continue

        closing = _find_unescaped_closing_bracket(value, position + 1)
        if closing is None:
            text_buffer.append(character)
            position += 1
            continue
        raw_tag = value[position + 1 : closing].strip()
        if not raw_tag:
            text_buffer.append("[]")
            position = closing + 1
            continue
        flush_text()

        if raw_tag.startswith("/"):
            closing_name = raw_tag[1:].strip().casefold()
            if len(stack) > 1 and stack[-1][0] == closing_name:
                stack.pop()
            else:
                stack[-1][1].append(_DslLiteral(value[position : closing + 1]))
            position = closing + 1
            continue

        pieces = raw_tag.split(None, 1)
        name = pieces[0].casefold()
        argument = pieces[1].strip() if len(pieces) == 2 else ""
        node = _DslTag(name=name, argument=argument)
        stack[-1][1].append(node)
        if name != "br":
            stack.append((name, node.children))
        position = closing + 1

    flush_text()
    return root


def _render_dsl(value: str, headword: str, dictionary_id: str) -> str:
    return _render_dsl_nodes(_parse_dsl_nodes(value), headword, dictionary_id)


def _render_dsl_nodes(
    nodes: list[_DslNode],
    headword: str,
    dictionary_id: str,
) -> str:
    rendered: list[str] = []
    for node in nodes:
        if isinstance(node, _DslText):
            escaped = html.escape(node.value, quote=False)
            escaped = escaped.replace("~", html.escape(headword, quote=False))
            rendered.append(escaped.replace("\n", "<p></p>"))
            continue
        if isinstance(node, _DslLiteral):
            rendered.append(html.escape(node.value, quote=False).replace("\n", "<p></p>"))
            continue
        rendered.append(_render_dsl_tag(node, headword, dictionary_id))
    return "".join(rendered)


def _render_dsl_tag(node: _DslTag, headword: str, dictionary_id: str) -> str:
    inner = _render_dsl_nodes(node.children, headword, dictionary_id)
    name = node.name

    # These class names intentionally match GoldenDict-ng's DSL renderer.
    simple_tags = {
        "b": ("b", "dsl_b"),
        "i": ("i", "dsl_i"),
        "u": ("span", "dsl_u"),
        "*": ("span", "dsl_opt"),
        "trn": ("span", "dsl_trn"),
        "ex": ("span", "dsl_ex"),
        "com": ("span", "dsl_com"),
        "!trs": ("span", "dsl_trs"),
        "p": ("span", "dsl_p"),
        "t": ("span", "dsl_t"),
        "lang": ("span", "dsl_lang"),
        "sub": ("sub", "dsl_sub"),
        "sup": ("sup", "dsl_sup"),
    }
    if name in simple_tags:
        element, class_name = simple_tags[name]
        return f'<{element} class="{class_name}">{inner}</{element}>'
    if _MARGIN_TAG_RE.fullmatch(name):
        return f'<div class="dsl_{name}">{inner}</div>'
    if name == "br":
        return "<br>"
    if name == "c":
        color = _unquote(node.argument)
        if color and _COLOR_RE.fullmatch(color):
            return f'<font class="dsl_c" color="{html.escape(color, quote=True)}">{inner}</font>'
        return f'<span class="c_default_color">{inner}</span>'
    if name == "'":
        return (
            '<span class="dsl_stress">'
            f'<span class="dsl_stress_without_accent">{inner}</span>'
            f'<span class="dsl_stress_with_accent">{inner}&#x301;</span>'
            "</span>"
        )
    if name == "ref":
        target = _tag_target(node, headword)
        if not target:
            return f'<span class="dsl_ref">{inner}</span>'
        # ``transform_article_html`` turns this into the shared lookup marker.
        href = f"bword://{quote(target, safe='')}"
        return f'<a class="dsl_ref" href="{html.escape(href, quote=True)}">{inner}</a>'
    if name == "url":
        target = _tag_target(node, headword)
        parsed = urlsplit(target)
        if parsed.scheme.casefold() not in {"http", "https", "mailto"}:
            return f'<span class="dsl_url">{inner}</span>'
        return f'<a class="dsl_url" href="{html.escape(target, quote=True)}">{inner}</a>'
    if name == "s":
        target = _tag_target(node, headword)
        logical_path = _safe_embedded_resource_path(target)
        if logical_path is None:
            return f'<span class="dsl_s">{inner}</span>'
        encoded_path = quote(logical_path, safe="/")
        suffix = PurePosixPath(logical_path).suffix.casefold()
        label = inner or html.escape(PurePosixPath(logical_path).name)
        if suffix in _AUDIO_EXTENSIONS:
            href = f"gdau:///{encoded_path}"
            return f'<span class="dsl_s_wav"><a href="{href}">{label}</a></span>'
        href = f"bres:///{encoded_path}"
        if suffix in _IMAGE_EXTENSIONS:
            alt = html.escape(PurePosixPath(logical_path).name, quote=True)
            return f'<span class="dsl_s"><img src="{href}" alt="{alt}"></span>'
        return f'<a class="dsl_s" href="{href}">{label}</a>'
    return f'<span class="dsl_unknown">{inner}</span>'


def _tag_target(node: _DslTag, headword: str) -> str:
    argument = _unquote(node.argument)
    if argument:
        key_value = re.fullmatch(r"(?:target|href)\s*=\s*(.+)", argument, re.I)
        return _unquote(key_value.group(1)) if key_value else argument
    return _plain_nodes(node.children, headword).strip()


def _plain_nodes(nodes: list[_DslNode], headword: str) -> str:
    result: list[str] = []
    for node in nodes:
        if isinstance(node, _DslText):
            result.append(node.value.replace("~", headword))
        elif isinstance(node, _DslLiteral):
            result.append(node.value)
        else:
            result.append(_plain_nodes(node.children, headword))
    return "".join(result)


def _safe_embedded_resource_path(value: str) -> str | None:
    parts = _safe_resource_parts(value)
    if parts is None:
        return None
    return "/".join(parts)


def _safe_resource_parts(resource_path: str) -> tuple[str, ...] | None:
    if not isinstance(resource_path, str) or "\x00" in resource_path:
        return None
    decoded = unquote(resource_path).replace("\\", "/")
    if not decoded or decoded.startswith("/"):
        return None
    path = PurePosixPath(decoded)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.parts


def _contained_file(root: Path, parts: tuple[str, ...]) -> Path | None:
    try:
        candidate = root.joinpath(*parts).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None
