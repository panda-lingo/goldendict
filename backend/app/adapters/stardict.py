"""StarDict dictionary reader.

Index/field parsing and HTML compatibility live together here on purpose.  The
field semantics and ``sdct_*`` wrappers track
``goldendict-ng/src/dict/stardict.cc``; keeping that boundary local makes
future upstream format updates straightforward.
"""

from __future__ import annotations

import bisect
import gzip
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import BinaryIO
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


_IFO_MAGIC = "StarDict's dict ifo file"
_MAX_IFO_BYTES = 1024 * 1024
_MAX_INDEX_WORD_BYTES = 1024 * 1024
_MAX_RECORD_BYTES = 64 * 1024 * 1024
_SAFE_COLOR_RE = re.compile(r"(?:#[0-9a-fA-F]{3,8}|[A-Za-z]{1,32})\Z")
_CSS_URL_RE = re.compile(r"url\(\s*([\"']?)([^\"')]+)\1\s*\)", re.I)
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


class StarDictReadError(RuntimeError):
    """Raised when a loaded StarDict bundle cannot be read safely."""


@dataclass(frozen=True, slots=True)
class _StarEntry:
    word: str
    offset: int
    size: int


class StarDictAdapter(DictionaryAdapter):
    """A thread-safe reader for a StarDict ``.ifo`` dictionary bundle."""

    format_name = "stardict"

    def __init__(
        self,
        path: str | Path,
        dictionary_id: str | None = None,
        *,
        name: str | None = None,
        max_resource_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        self._ifo_path = Path(path).expanduser().resolve()
        if not self.supports(self._ifo_path):
            raise UnsupportedDictionaryFormat(f"expected a .ifo file: {self._ifo_path}")
        if not self._ifo_path.is_file():
            raise FileNotFoundError(self._ifo_path)

        self._properties = _read_ifo(self._ifo_path)
        same_type_sequence = self._properties.get("sametypesequence", "")
        if any(not character.isascii() or not character.isalpha() for character in same_type_sequence):
            raise UnsupportedDictionaryFormat("invalid StarDict sametypesequence")
        offset_bits = _parse_offset_bits(self._properties.get("idxoffsetbits", "32"))
        self._same_type_sequence = same_type_sequence
        self._idx_path = _find_companion(self._ifo_path, (".idx", ".idx.gz"))
        self._dict_path = _find_companion(self._ifo_path, (".dict", ".dict.dz"))
        self._dict_is_compressed = self._dict_path.name.casefold().endswith(".dz")

        mutable_index, entries, display_words = self._read_index(offset_bits)
        synonym_path = _find_companion(
            self._ifo_path,
            (".syn",),
            required=False,
        )
        if synonym_path is not None:
            synonym_count = self._read_synonyms(
                synonym_path,
                mutable_index,
                entries,
                display_words,
            )
            _validate_declared_count(self._properties, "synwordcount", synonym_count)
        else:
            _validate_declared_count(self._properties, "synwordcount", 0)

        self._index = {key: tuple(values) for key, values in mutable_index.items()}
        ordered = sorted(display_words.items(), key=lambda item: (item[0], item[1]))
        self._suggestion_keys = tuple(item[0] for item in ordered)
        self._suggestion_words = tuple(item[1] for item in ordered)
        self._resource_roots = self._find_resource_roots()
        self._max_resource_bytes = max(0, max_resource_bytes)

        resolved_id = dictionary_id or stable_dictionary_id(self.format_name, self._ifo_path)
        self._dictionary_id = resolved_id
        self.metadata = DictionaryMetadata(
            dictionary_id=resolved_id,
            name=name or self._properties.get("bookname") or self._ifo_path.stem,
            format=self.format_name,
            word_count=len(display_words),
            main_path=self._ifo_path,
        )

    @classmethod
    def supports(cls, path: str | Path) -> bool:
        return str(path).casefold().endswith(".ifo")

    def lookup(self, word: str) -> DictionaryArticle | None:
        key = _lookup_key(word)
        if not key:
            return None
        entries = self._index.get(key)
        if not entries:
            return None

        rendered: list[str] = []
        seen: set[tuple[int, int]] = set()
        for entry in entries:
            identity = (entry.offset, entry.size)
            if identity in seen:
                continue
            seen.add(identity)
            record = self._read_record(entry)
            rendered.append(
                _render_fields(
                    _parse_fields(record, self._same_type_sequence),
                    self._dictionary_id,
                )
            )
        transformed = transform_article_html("".join(rendered), self._dictionary_id)
        return DictionaryArticle(
            html=transformed,
            headword=self._display_for_key(key),
        )

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
                raise StarDictReadError("dictionary resource exceeds the configured size limit")
            body = candidate.read_bytes()
            if len(body) > self._max_resource_bytes:
                raise StarDictReadError("dictionary resource exceeds the configured size limit")
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

    def _display_for_key(self, key: str) -> str:
        position = bisect.bisect_left(self._suggestion_keys, key)
        if position < len(self._suggestion_keys) and self._suggestion_keys[position] == key:
            return self._suggestion_words[position]
        return self._index[key][0].word

    def _read_index(
        self,
        offset_bits: int,
    ) -> tuple[dict[str, list[_StarEntry]], list[_StarEntry], dict[str, str]]:
        width = offset_bits // 8
        index: dict[str, list[_StarEntry]] = {}
        entries: list[_StarEntry] = []
        display_words: dict[str, str] = {}
        with _open_maybe_gzip(self._idx_path) as source:
            while True:
                word_bytes = _read_c_string(source)
                if word_bytes is None:
                    break
                trailer = source.read(width + 4)
                if len(trailer) != width + 4:
                    raise UnsupportedDictionaryFormat(
                        f"truncated StarDict index entry in {self._idx_path}"
                    )
                word = word_bytes.decode("utf-8", errors="replace")
                offset = int.from_bytes(trailer[:width], "big")
                size = int.from_bytes(trailer[width:], "big")
                if size > _MAX_RECORD_BYTES:
                    raise UnsupportedDictionaryFormat(
                        f"StarDict record exceeds {_MAX_RECORD_BYTES} bytes"
                    )
                entry = _StarEntry(word=word, offset=offset, size=size)
                entries.append(entry)
                key = _lookup_key(word)
                if not key:
                    continue
                index.setdefault(key, []).append(entry)
                display_words.setdefault(key, word)
            index_size = source.tell()
        _validate_declared_count(self._properties, "wordcount", len(entries))
        _validate_declared_count(self._properties, "idxfilesize", index_size)
        return index, entries, display_words

    @staticmethod
    def _read_synonyms(
        path: Path,
        index: dict[str, list[_StarEntry]],
        entries: list[_StarEntry],
        display_words: dict[str, str],
    ) -> int:
        count = 0
        with path.open("rb") as source:
            while True:
                synonym_bytes = _read_c_string(source)
                if synonym_bytes is None:
                    break
                number_bytes = source.read(4)
                if len(number_bytes) != 4:
                    raise UnsupportedDictionaryFormat(
                        f"truncated StarDict synonym entry in {path}"
                    )
                entry_number = int.from_bytes(number_bytes, "big")
                if entry_number >= len(entries):
                    raise UnsupportedDictionaryFormat(
                        f"StarDict synonym points outside the index in {path}"
                    )
                count += 1
                synonym = synonym_bytes.decode("utf-8", errors="replace")
                key = _lookup_key(synonym)
                if not key:
                    continue
                target = entries[entry_number]
                values = index.setdefault(key, [])
                if target not in values:
                    values.append(target)
                display_words.setdefault(key, synonym)
        return count

    def _read_record(self, entry: _StarEntry) -> bytes:
        if entry.size > _MAX_RECORD_BYTES:
            raise UnsupportedDictionaryFormat(
                f"StarDict record exceeds {_MAX_RECORD_BYTES} bytes"
            )
        if self._dict_is_compressed:
            source_context = gzip.open(self._dict_path, "rb")
        else:
            source_context = self._dict_path.open("rb")
        with source_context as source:
            source.seek(entry.offset)
            body = source.read(entry.size)
        if len(body) != entry.size:
            raise UnsupportedDictionaryFormat(
                f"truncated StarDict record for {entry.word!r}"
            )
        return body

    def _find_resource_roots(self) -> tuple[Path, ...]:
        base = self._ifo_path.with_suffix("")
        dictionary_directory = self._ifo_path.parent.resolve()
        candidates = (
            self._ifo_path.parent / "res",
            Path(str(base) + ".res"),
            Path(str(self._ifo_path) + ".res"),
        )
        roots: list[Path] = []
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
            roots.append(resolved)
        return tuple(roots)


# Alternative spelling commonly used by integrations.
StardictAdapter = StarDictAdapter


def _read_ifo(path: Path) -> dict[str, str]:
    if path.stat().st_size > _MAX_IFO_BYTES:
        raise UnsupportedDictionaryFormat("StarDict .ifo exceeds the safety limit")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedDictionaryFormat(f"invalid UTF-8 StarDict .ifo: {path}") from error
    lines = text.splitlines()
    if not lines or lines[0].strip() != _IFO_MAGIC:
        raise UnsupportedDictionaryFormat(f"invalid StarDict .ifo header: {path}")
    properties: dict[str, str] = {}
    for line in lines[1:]:
        key, separator, value = line.partition("=")
        if separator and key.strip():
            properties[key.strip().casefold()] = value.strip()
    return properties


def _parse_offset_bits(value: str) -> int:
    try:
        bits = int(value)
    except ValueError as error:
        raise UnsupportedDictionaryFormat(f"invalid StarDict idxoffsetbits: {value!r}") from error
    if bits not in {32, 64}:
        raise UnsupportedDictionaryFormat(
            f"StarDict idxoffsetbits must be 32 or 64, got {bits}"
        )
    return bits


def _validate_declared_count(
    properties: dict[str, str],
    property_name: str,
    actual: int,
) -> None:
    value = properties.get(property_name)
    if value is None:
        return
    try:
        declared = int(value)
    except ValueError as error:
        raise UnsupportedDictionaryFormat(
            f"invalid StarDict {property_name}: {value!r}"
        ) from error
    if declared < 0 or declared != actual:
        raise UnsupportedDictionaryFormat(
            f"StarDict {property_name} declares {declared}, found {actual}"
        )


def _find_companion(
    ifo_path: Path,
    suffixes: tuple[str, ...],
    *,
    required: bool = True,
) -> Path | None:
    base = ifo_path.with_suffix("")
    dictionary_directory = ifo_path.parent.resolve()
    for suffix in suffixes:
        candidate = Path(str(base) + suffix)
        if candidate.is_file():
            try:
                resolved = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            try:
                resolved.relative_to(dictionary_directory)
            except ValueError:
                continue
            return resolved

    try:
        names = {child.name.casefold(): child for child in ifo_path.parent.iterdir()}
    except OSError:
        names = {}
    for suffix in suffixes:
        candidate = names.get(f"{base.name}{suffix}".casefold())
        if candidate is not None and candidate.is_file():
            try:
                resolved = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            try:
                resolved.relative_to(dictionary_directory)
            except ValueError:
                continue
            return resolved
    if required:
        choices = ", ".join(f"{base.name}{suffix}" for suffix in suffixes)
        raise FileNotFoundError(f"missing StarDict companion ({choices})")
    return None


def _open_maybe_gzip(path: Path) -> BinaryIO:
    if path.name.casefold().endswith(".gz"):
        return gzip.open(path, "rb")
    return path.open("rb")


def _read_c_string(source: BinaryIO) -> bytes | None:
    value = bytearray()
    while True:
        character = source.read(1)
        if character == b"":
            if not value:
                return None
            raise UnsupportedDictionaryFormat("unterminated StarDict string")
        if character == b"\x00":
            return bytes(value)
        value.extend(character)
        if len(value) > _MAX_INDEX_WORD_BYTES:
            raise UnsupportedDictionaryFormat(
                f"StarDict index word exceeds {_MAX_INDEX_WORD_BYTES} bytes"
            )


def _lookup_key(value: str) -> str:
    return normalize_headword(value)


def _parse_fields(record: bytes, same_type_sequence: str) -> list[tuple[str, bytes]]:
    if same_type_sequence:
        return _parse_same_type_fields(record, same_type_sequence)
    return _parse_typed_fields(record)


def _parse_same_type_fields(record: bytes, sequence: str) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, bytes]] = []
    position = 0
    for field_number, field_type in enumerate(sequence):
        last = field_number == len(sequence) - 1
        if last:
            fields.append((field_type, record[position:]))
            position = len(record)
            break
        if field_type.islower():
            terminator = record.find(b"\x00", position)
            if terminator < 0:
                raise UnsupportedDictionaryFormat(
                    "unterminated textual field in StarDict record"
                )
            fields.append((field_type, record[position:terminator]))
            position = terminator + 1
            continue
        if position + 4 > len(record):
            raise UnsupportedDictionaryFormat("truncated binary StarDict field length")
        size = int.from_bytes(record[position : position + 4], "big")
        position += 4
        if position + size > len(record):
            raise UnsupportedDictionaryFormat("truncated binary StarDict field")
        fields.append((field_type, record[position : position + size]))
        position += size
    return fields


def _parse_typed_fields(record: bytes) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, bytes]] = []
    position = 0
    while position < len(record):
        type_byte = record[position]
        position += 1
        field_type = chr(type_byte)
        if field_type.islower():
            terminator = record.find(b"\x00", position)
            if terminator < 0:
                # A few generators omit the final NUL; the idx size still gives
                # an unambiguous boundary, so accept that final textual field.
                fields.append((field_type, record[position:]))
                break
            fields.append((field_type, record[position:terminator]))
            position = terminator + 1
            continue
        if position + 4 > len(record):
            raise UnsupportedDictionaryFormat("truncated binary StarDict field length")
        size = int.from_bytes(record[position : position + 4], "big")
        position += 4
        if position + size > len(record):
            raise UnsupportedDictionaryFormat("truncated binary StarDict field")
        fields.append((field_type, record[position : position + size]))
        position += size
    return fields


def _render_fields(fields: list[tuple[str, bytes]], dictionary_id: str) -> str:
    rendered: list[str] = []
    for field_type, body in fields:
        if not field_type.islower():
            # Upper-case StarDict fields are opaque binary payloads.  They must
            # never be interpolated into HTML; associated media belongs in res/.
            continue
        text = body.decode("utf-8", errors="replace")
        if field_type == "h":
            converted = _rewrite_html_resources(text, dictionary_id)
            rendered.append(f'<div class="sdct_h">{converted}</div>')
        elif field_type in {"m", "l"}:
            rendered.append(
                f'<div class="sdct_{field_type}">{_escaped_text(text)}</div>'
            )
        elif field_type == "g":
            rendered.append(
                f'<div class="sdct_g">{_render_pango(text)}</div>'
            )
        elif field_type == "r":
            rendered.append(_render_resource_list(text, dictionary_id))
        else:
            safe_type = field_type if field_type.isascii() and field_type.isalnum() else "unknown"
            rendered.append(
                f'<div class="sdct_{safe_type}">{_escaped_text(text)}</div>'
            )
    return "".join(rendered)


def _escaped_text(value: str) -> str:
    return html.escape(value, quote=False).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


class _HtmlResourceRewriter(HTMLParser):
    def __init__(self, dictionary_id: str) -> None:
        super().__init__(convert_charrefs=False)
        self.dictionary_id = dictionary_id
        self.output: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.output.append(self._start_tag(tag, attrs, closed=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.output.append(self._start_tag(tag, attrs, closed=True))

    def _start_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        closed: bool,
    ) -> str:
        rendered_attrs: list[str] = []
        lowered_tag = tag.casefold()
        for attribute, value in attrs:
            if value is None:
                rendered_attrs.append(attribute)
                continue
            lowered_attribute = attribute.casefold()
            rewritten = value
            if lowered_attribute in {"src", "poster", "data"}:
                rewritten = _rewrite_resource_url(
                    value,
                    self.dictionary_id,
                    tag=lowered_tag,
                )
            elif lowered_attribute == "href" and lowered_tag in {"a", "area"}:
                rewritten = _rewrite_article_anchor(value)
            elif lowered_attribute == "href" and lowered_tag == "link":
                rewritten = _rewrite_resource_url(
                    value,
                    self.dictionary_id,
                    tag=lowered_tag,
                )
            elif lowered_attribute == "style":
                rewritten = _rewrite_css_urls(value, self.dictionary_id)
            rendered_attrs.append(
                f'{attribute}="{html.escape(rewritten, quote=True)}"'
            )
        attributes = f" {' '.join(rendered_attrs)}" if rendered_attrs else ""
        ending = "/>" if closed else ">"
        return f"<{tag}{attributes}{ending}"

    def handle_endtag(self, tag: str) -> None:
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.output.append(f"<!{decl}>")


def _rewrite_html_resources(value: str, dictionary_id: str) -> str:
    parser = _HtmlResourceRewriter(dictionary_id)
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError):
        return html.escape(value, quote=False)
    return "".join(parser.output)


def _rewrite_css_urls(value: str, dictionary_id: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        delimiter = match.group(1)
        rewritten = _rewrite_resource_url(
            match.group(2).strip(),
            dictionary_id,
            tag="style",
        )
        return f"url({delimiter}{rewritten}{delimiter})"

    return _CSS_URL_RE.sub(replacement, value)


def _rewrite_article_anchor(value: str) -> str:
    """Treat scheme-less StarDict anchors as word lookups, like upstream."""

    stripped = value.strip()
    if not stripped or stripped.startswith(("#", "//")):
        return value
    scheme = urlsplit(stripped).scheme.casefold()
    if scheme:
        if scheme in {"javascript", "vbscript", "file"}:
            return "#"
        return value
    return f"bword://{quote(unquote(stripped), safe='')}"


def _rewrite_resource_url(value: str, dictionary_id: str, *, tag: str) -> str:
    stripped = value.strip()
    if not stripped or stripped.startswith(("#", "//")):
        return value
    parsed = urlsplit(stripped)
    scheme = parsed.scheme.casefold()
    if scheme:
        if scheme in {"javascript", "vbscript", "file"}:
            return "#"
        return value
    if stripped.startswith("/"):
        return "#"
    parts = _safe_resource_parts(parsed.path)
    if parts is None:
        return "#"
    logical_path = "/".join(parts)
    suffix = PurePosixPath(logical_path).suffix.casefold()
    resource_scheme = "gdau" if tag in {"audio", "source"} or suffix in _AUDIO_EXTENSIONS else "bres"
    # The common article transformer supplies the current dictionary ID.  An
    # empty authority prevents it from mistaking the ID for part of the key.
    rewritten = f"{resource_scheme}:///{quote(logical_path, safe='/')}"
    if parsed.query:
        rewritten += f"?{parsed.query}"
    if parsed.fragment:
        rewritten += f"#{parsed.fragment}"
    return rewritten


class _PangoRenderer(HTMLParser):
    _SIMPLE_TAGS = {"b", "strong", "i", "em", "u", "sub", "sup", "small", "big"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered == "br":
            self.output.append("<br>")
            return
        if lowered in self._SIMPLE_TAGS:
            normalized = {"strong": "b", "em": "i"}.get(lowered, lowered)
            self.output.append(f"<{normalized}>")
            self.stack.append(normalized)
            return
        if lowered == "span":
            styles: list[str] = []
            for name, value in attrs:
                if value is None:
                    continue
                lowered_name = name.casefold()
                if lowered_name in {"foreground", "color", "background"} and _SAFE_COLOR_RE.fullmatch(value):
                    property_name = "background-color" if lowered_name == "background" else "color"
                    styles.append(f"{property_name}:{value}")
                elif lowered_name == "weight" and value.casefold() in {"bold", "heavy"}:
                    styles.append("font-weight:bold")
                elif lowered_name == "style" and value.casefold() in {"italic", "oblique"}:
                    styles.append(f"font-style:{value.casefold()}")
            style = f' style="{html.escape(";".join(styles), quote=True)}"' if styles else ""
            self.output.append(f"<span{style}>")
            self.stack.append("span")

    def handle_endtag(self, tag: str) -> None:
        normalized = {"strong": "b", "em": "i"}.get(tag.casefold(), tag.casefold())
        if self.stack and self.stack[-1] == normalized:
            self.stack.pop()
            self.output.append(f"</{normalized}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")


def _render_pango(value: str) -> str:
    parser = _PangoRenderer()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError):
        return _escaped_text(value)
    while parser.stack:
        parser.output.append(f"</{parser.stack.pop()}>")
    return "".join(parser.output).replace("\n", "<br>")


def _render_resource_list(value: str, dictionary_id: str) -> str:
    rendered: list[str] = []
    for item in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not item:
            continue
        resource_type, separator, path = item.partition(":")
        if not separator:
            resource_type, path = "att", item
        parts = _safe_resource_parts(path.strip())
        if parts is None:
            rendered.append(html.escape(item, quote=False))
            continue
        logical_path = "/".join(parts)
        encoded_path = quote(logical_path, safe="/")
        label = html.escape(PurePosixPath(logical_path).name, quote=False)
        lowered_type = resource_type.strip().casefold()
        if lowered_type == "img":
            rendered.append(
                f'<img src="bres:///{encoded_path}" alt="{html.escape(PurePosixPath(logical_path).name, quote=True)}">'
            )
        elif lowered_type == "snd":
            rendered.append(f'<a href="gdau:///{encoded_path}">{label}</a>')
        elif lowered_type == "vdo":
            rendered.append(f'<a href="gdvideo:///{encoded_path}">{label}</a>')
        else:
            rendered.append(f'<a href="bres:///{encoded_path}">{label}</a>')
    return f'<div class="sdct_r">{"<br>".join(rendered)}</div>'


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
