"""Lazy, bounded-memory MDict (MDX/MDD) adapter."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
import html as html_module
from pathlib import Path
import re
from struct import pack, unpack
from threading import RLock
from typing import Any
import zlib

import lzo
from bs4 import BeautifulSoup
from readmdict import MDD, MDX

from ..text import display_text, normalize_headword, normalize_resource_key
from ..transform import (
    decode_css,
    etag_for,
    media_type_for,
    rewrite_css_urls,
    transform_article_html,
)
from .base import (
    DictionaryAdapter,
    DictionaryArticle,
    DictionaryMetadata,
    DictionaryResource,
    stable_dictionary_id,
)


_MDD_VOLUME = re.compile(r"^(?P<stem>.+?)(?:\.(?P<volume>\d+))?\.mdd$", re.IGNORECASE)
_REDIRECT = re.compile(r"^\s*@@@LINK\s*=\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
_MDD_REDIRECT_PREFIX = b"@\x00@\x00@\x00L\x00I\x00N\x00K\x00=\x00"
_SIDE_CAR_SUFFIXES = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".bmp",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".mp4",
    ".webm",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
}


class MDictReadError(RuntimeError):
    """Raised for a corrupt or unsupported MDict record block."""


@dataclass(frozen=True, slots=True)
class _Block:
    file_offset: int
    compressed_size: int
    decompressed_size: int
    logical_start: int
    logical_end: int


class _LazyRecordFile:
    """Random-access record reader using readmdict's already-parsed key index."""

    def __init__(self, reader: MDX | MDD, cache_bytes: int, max_block_bytes: int) -> None:
        self.reader = reader
        self._cache_limit = max(0, cache_bytes)
        self._max_block_bytes = max(0, max_block_bytes)
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._cache_size = 0
        self._lock = RLock()
        self._blocks = self._read_block_table()
        self._block_ends = [block.logical_end for block in self._blocks]
        self._total_size = self._blocks[-1].logical_end if self._blocks else 0

    @property
    def keys(self) -> list[tuple[int, bytes]]:
        return self.reader._key_list  # noqa: SLF001 - pinned readmdict integration

    def record(self, index: int, *, max_output_bytes: int | None = None) -> bytes:
        if index < 0 or index >= len(self.keys):
            raise IndexError("MDict record index is out of range")
        start = self.keys[index][0]
        end = self.keys[index + 1][0] if index + 1 < len(self.keys) else self._total_size
        if not 0 <= start <= end <= self._total_size:
            raise MDictReadError("MDict record offsets are corrupt")
        if max_output_bytes is not None and end - start > max(0, max_output_bytes):
            raise MDictReadError("MDict record exceeds the configured output size limit")

        chunks: list[bytes] = []
        cursor = start
        while cursor < end:
            block_index = bisect_right(self._block_ends, cursor)
            if block_index >= len(self._blocks):
                raise MDictReadError("MDict record points past the record blocks")
            block = self._blocks[block_index]
            data = self._block(block_index)
            local_start = cursor - block.logical_start
            local_end = min(end, block.logical_end) - block.logical_start
            chunks.append(data[local_start:local_end])
            cursor = block.logical_start + local_end
        return b"".join(chunks)

    def close(self) -> None:
        """Drop only caches; record calls remain valid and reopen the file."""

        with self._lock:
            self._cache.clear()
            self._cache_size = 0

    def _read_block_table(self) -> list[_Block]:
        reader = self.reader
        with open(reader._fname, "rb") as source:  # noqa: SLF001
            source.seek(reader._record_block_offset)  # noqa: SLF001
            block_count = reader._read_number(source)  # noqa: SLF001
            entry_count = reader._read_number(source)  # noqa: SLF001
            if entry_count != reader._num_entries:  # noqa: SLF001
                raise MDictReadError("MDict record/key entry counts disagree")
            info_size = reader._read_number(source)  # noqa: SLF001
            declared_data_size = reader._read_number(source)  # noqa: SLF001
            pairs: list[tuple[int, int]] = []
            for _ in range(block_count):
                compressed_size = reader._read_number(source)  # noqa: SLF001
                decompressed_size = reader._read_number(source)  # noqa: SLF001
                if (
                    compressed_size > self._max_block_bytes
                    or decompressed_size > self._max_block_bytes
                ):
                    raise MDictReadError("MDict record block exceeds the configured size limit")
                pairs.append((compressed_size, decompressed_size))
            if info_size != block_count * reader._number_width * 2:  # noqa: SLF001
                raise MDictReadError("MDict record block table has an invalid size")
            file_offset = source.tell()

        blocks: list[_Block] = []
        logical_offset = 0
        compressed_total = 0
        for compressed_size, decompressed_size in pairs:
            blocks.append(
                _Block(
                    file_offset=file_offset,
                    compressed_size=compressed_size,
                    decompressed_size=decompressed_size,
                    logical_start=logical_offset,
                    logical_end=logical_offset + decompressed_size,
                )
            )
            file_offset += compressed_size
            logical_offset += decompressed_size
            compressed_total += compressed_size
        if compressed_total != declared_data_size:
            raise MDictReadError("MDict record data size does not match its block table")
        return blocks

    def _block(self, index: int) -> bytes:
        with self._lock:
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached

            block = self._blocks[index]
            with open(self.reader._fname, "rb") as source:  # noqa: SLF001
                source.seek(block.file_offset)
                compressed = source.read(block.compressed_size)
            if len(compressed) != block.compressed_size or len(compressed) < 8:
                raise MDictReadError("MDict record block is truncated")
            kind = compressed[:4]
            checksum = unpack(">I", compressed[4:8])[0]
            if kind == b"\x00\x00\x00\x00":
                decompressed = compressed[8:]
            elif kind == b"\x01\x00\x00\x00":
                header = b"\xf0" + pack(">I", block.decompressed_size)
                decompressed = lzo.decompress(header + compressed[8:])
            elif kind == b"\x02\x00\x00\x00":
                decompressed = _decompress_zlib_limited(
                    compressed[8:],
                    block.decompressed_size,
                )
            else:
                raise MDictReadError(f"unsupported MDict compression marker: {kind.hex()}")
            if len(decompressed) != block.decompressed_size:
                raise MDictReadError("MDict decompressed block has an invalid size")
            if zlib.adler32(decompressed) & 0xFFFFFFFF != checksum:
                raise MDictReadError("MDict record block checksum failed")

            if len(decompressed) <= self._cache_limit:
                while self._cache and self._cache_size + len(decompressed) > self._cache_limit:
                    _, evicted = self._cache.popitem(last=False)
                    self._cache_size -= len(evicted)
                self._cache[index] = decompressed
                self._cache_size += len(decompressed)
            return decompressed


@dataclass(slots=True)
class _HeadwordEntry:
    display: str
    record_indexes: list[int]


@dataclass(frozen=True, slots=True)
class _MDDLocation:
    volume: int
    record_index: int
    display_path: str


class MDictAdapter(DictionaryAdapter):
    format_name = "mdict"

    def __init__(
        self,
        main_path: Path,
        *,
        name: str | None = None,
        cache_bytes: int = 32 * 1024 * 1024,
        max_block_bytes: int = 128 * 1024 * 1024,
        max_article_bytes: int = 32 * 1024 * 1024,
        max_resource_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        path = main_path.resolve(strict=True)
        if path.suffix.casefold() != ".mdx":
            raise ValueError("MDict main file must have the .mdx extension")
        self._dictionary_id = stable_dictionary_id(self.format_name, path)
        self._max_article_bytes = max(0, max_article_bytes)
        self._max_resource_bytes = max(0, max_resource_bytes)
        self._max_block_bytes = max(0, max_block_bytes)
        self._mdx = MDX(str(path), substyle=False)
        self._records = _LazyRecordFile(self._mdx, cache_bytes, self._max_block_bytes)
        self._encoding = getattr(self._mdx, "_encoding", "utf-8") or "utf-8"
        self._styles = _parse_stylesheets(self._mdx.header)
        self._headwords = self._build_headword_index()
        self._sorted_headwords = sorted(self._headwords)
        self._mdd_readers: list[_LazyRecordFile] = []
        self._mdd_resources: dict[str, _MDDLocation] = {}
        self._load_mdd_volumes(path, cache_bytes, self._max_block_bytes)
        self._sidecars = _discover_sidecars(path)

        title = name or _clean_title(_header_value(self._mdx.header, "Title")) or path.stem
        source_language = _first_header(
            self._mdx.header,
            "SourceLanguage",
            "SourceLang",
            "LangFrom",
        )
        target_language = _first_header(
            self._mdx.header,
            "TargetLanguage",
            "TargetLang",
            "LangTo",
        )
        icon_path = _find_icon_resource(self._sidecars, path.stem)
        self.metadata = DictionaryMetadata(
            dictionary_id=self._dictionary_id,
            name=title,
            format=self.format_name,
            word_count=len(self._records.keys),
            main_path=path,
            source_language=source_language,
            target_language=target_language,
            icon_resource_path=icon_path,
        )

    def lookup(self, word: str) -> DictionaryArticle | None:
        normalized = normalize_headword(word)
        if not normalized:
            return None
        raw_articles = self._resolve_word(
            normalized,
            visited=set(),
            depth=0,
            remaining_bytes=[self._max_article_bytes],
        )
        if not raw_articles:
            return None
        fragments = [f'<div class="mdict">{article}</div>' for article in _unique(raw_articles)]
        transformed = transform_article_html("\n".join(fragments), self._dictionary_id)
        entry = self._headwords.get(normalized)
        return DictionaryArticle(html=transformed, headword=entry.display if entry else word)

    def suggestions(self, prefix: str, limit: int) -> list[str]:
        normalized = normalize_headword(prefix)
        if not normalized or limit <= 0:
            return []
        limit = min(limit, 100)
        position = bisect_left(self._sorted_headwords, normalized)
        suggestions: list[str] = []
        while position < len(self._sorted_headwords) and len(suggestions) < limit:
            candidate = self._sorted_headwords[position]
            if not candidate.startswith(normalized):
                break
            suggestions.append(self._headwords[candidate].display)
            position += 1
        return suggestions

    def resource(self, resource_path: str) -> DictionaryResource | None:
        # Starlette has already URL-decoded a path parameter exactly once.
        try:
            key = normalize_resource_key(resource_path, decode_percent=False)
        except ValueError:
            return None
        body = self._mdd_resource(key, visited=set(), depth=0)
        if body is None:
            path = self._sidecars.get(key)
            if path is None:
                return None
            size = path.stat().st_size
            if size > self._max_resource_bytes:
                raise MDictReadError("dictionary resource exceeds the configured size limit")
            body = path.read_bytes()
        if len(body) > self._max_resource_bytes:
            raise MDictReadError("dictionary resource exceeds the configured size limit")
        media_type = media_type_for(key)
        if media_type.startswith("text/css"):
            css = decode_css(body, self._encoding)
            body = rewrite_css_urls(css, self._dictionary_id, resource_path=key).encode("utf-8")
            if len(body) > self._max_resource_bytes:
                raise MDictReadError("rewritten dictionary resource exceeds the configured size limit")
        return DictionaryResource(body=body, media_type=media_type, etag=etag_for(body))

    def close(self) -> None:
        self._records.close()
        for reader in self._mdd_readers:
            reader.close()

    def _build_headword_index(self) -> dict[str, _HeadwordEntry]:
        headwords: dict[str, _HeadwordEntry] = {}
        for index, (_, raw_key) in enumerate(self._records.keys):
            display = display_text(raw_key)
            normalized = normalize_headword(display)
            if not normalized:
                continue
            existing = headwords.get(normalized)
            if existing is None:
                headwords[normalized] = _HeadwordEntry(display=display, record_indexes=[index])
            else:
                existing.record_indexes.append(index)
        return headwords

    def _resolve_word(
        self,
        normalized: str,
        *,
        visited: set[str],
        depth: int,
        remaining_bytes: list[int],
    ) -> list[str]:
        if depth >= 16 or normalized in visited:
            return []
        entry = self._headwords.get(normalized)
        if entry is None:
            return []
        next_visited = {*visited, normalized}
        resolved: list[str] = []
        for record_index in entry.record_indexes:
            body = self._records.record(
                record_index,
                max_output_bytes=self._max_article_bytes,
            )
            text = body.decode(self._encoding, errors="replace").strip("\x00")
            redirect = _REDIRECT.match(text)
            if redirect:
                resolved.extend(
                    self._resolve_word(
                        normalize_headword(redirect.group(1)),
                        visited=next_visited,
                        depth=depth + 1,
                        remaining_bytes=remaining_bytes,
                    )
                )
            else:
                text = _substitute_styles(text, self._styles)
                output_size = len(text.encode("utf-8"))
                if output_size > remaining_bytes[0]:
                    raise MDictReadError("MDict article exceeds the configured size limit")
                remaining_bytes[0] -= output_size
                resolved.append(text)
        return resolved

    def _load_mdd_volumes(
        self,
        main_path: Path,
        cache_bytes: int,
        max_block_bytes: int,
    ) -> None:
        dictionary_directory = main_path.parent.resolve()
        candidates: list[tuple[int, str, Path]] = []
        for child in main_path.parent.iterdir():
            if not child.is_file():
                continue
            match = _MDD_VOLUME.match(child.name)
            if not match or match.group("stem").casefold() != main_path.stem.casefold():
                continue
            try:
                resolved = child.resolve(strict=True)
                resolved.relative_to(dictionary_directory)
            except (OSError, RuntimeError, ValueError):
                continue
            candidates.append((int(match.group("volume") or 0), child.name.casefold(), resolved))
        for _, _, mdd_path in sorted(candidates, key=lambda item: (item[0], item[1])):
            reader = _LazyRecordFile(MDD(str(mdd_path)), cache_bytes, max_block_bytes)
            volume = len(self._mdd_readers)
            self._mdd_readers.append(reader)
            for record_index, (_, raw_key) in enumerate(reader.keys):
                display_path = display_text(raw_key)
                try:
                    key = normalize_resource_key(display_path)
                except ValueError:
                    continue
                self._mdd_resources.setdefault(
                    key,
                    _MDDLocation(volume=volume, record_index=record_index, display_path=display_path),
                )

    def _mdd_resource(self, key: str, *, visited: set[str], depth: int) -> bytes | None:
        if depth >= 16 or key in visited:
            return None
        location = self._mdd_resources.get(key)
        if location is None:
            return None
        body = self._mdd_readers[location.volume].record(
            location.record_index,
            max_output_bytes=self._max_resource_bytes,
        )
        if body.startswith(_MDD_REDIRECT_PREFIX):
            target = body[len(_MDD_REDIRECT_PREFIX) :].decode("utf-16-le", errors="replace").strip("\x00 \r\n")
            try:
                target_key = normalize_resource_key(target)
            except ValueError:
                return None
            return self._mdd_resource(target_key, visited={*visited, key}, depth=depth + 1)
        return body


def _header_value(header: dict[Any, Any], key: str) -> str | None:
    wanted = key.casefold()
    for raw_key, raw_value in header.items():
        decoded_key = display_text(raw_key).casefold()
        if decoded_key == wanted:
            return html_module.unescape(display_text(raw_value))
    return None


def _first_header(header: dict[Any, Any], *keys: str) -> str | None:
    for key in keys:
        value = _header_value(header, key)
        if value:
            return value.strip()
    return None


def _clean_title(value: str | None) -> str | None:
    if not value or value == "Title (No HTML code allowed)":
        return None
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True) or None


def _parse_stylesheets(header: dict[Any, Any]) -> dict[str, tuple[str, str]]:
    value = _header_value(header, "StyleSheet")
    if not value:
        return {}
    lines = re.split(r"[\r\n]", value)
    styles: dict[str, tuple[str, str]] = {}
    for index in range(0, len(lines) - 2, 3):
        styles[lines[index]] = (
            html_module.unescape(lines[index + 1]),
            html_module.unescape(lines[index + 2]),
        )
    return styles


def _substitute_styles(text: str, styles: dict[str, tuple[str, str]]) -> str:
    if not styles:
        return text.rstrip("\x00")
    output: list[str] = []
    closing = ""
    position = 0
    for match in re.finditer(r"`(\d+)`", text):
        output.append(text[position : match.start()])
        style = styles.get(match.group(1))
        if style:
            output.extend((closing, style[0]))
            closing = style[1]
        else:
            output.append(closing)
            closing = ""
        position = match.end()
    output.extend((text[position:].rstrip("\x00"), closing))
    return "".join(output)


def _discover_sidecars(main_path: Path) -> dict[str, Path]:
    resources: dict[str, Path] = {}
    stem = main_path.stem.casefold()
    dictionary_directory = main_path.parent.resolve()
    for child in main_path.parent.iterdir():
        if not child.is_file() or child == main_path:
            continue
        if not child.stem.casefold().startswith(stem) or child.suffix.casefold() not in _SIDE_CAR_SUFFIXES:
            continue
        try:
            resolved = child.resolve(strict=True)
            resolved.relative_to(dictionary_directory)
            resources.setdefault(normalize_resource_key(child.name), resolved)
        except (OSError, RuntimeError, ValueError):
            continue
    return resources


def _find_icon_resource(sidecars: dict[str, Path], stem: str) -> str | None:
    for extension in (".svg", ".png", ".webp", ".jpg", ".jpeg", ".ico", ".bmp", ".gif"):
        key = f"{stem}{extension}".casefold()
        if key in sidecars:
            return key
    return None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _decompress_zlib_limited(payload: bytes, expected_size: int) -> bytes:
    """Inflate one zlib stream without ever returning more than declared."""

    decompressor = zlib.decompressobj()
    body = decompressor.decompress(payload, expected_size + 1)
    if (
        len(body) != expected_size
        or not decompressor.eof
        or decompressor.unconsumed_tail
        or decompressor.unused_data
    ):
        raise MDictReadError("MDict zlib block exceeds or disagrees with its declared size")
    return body
