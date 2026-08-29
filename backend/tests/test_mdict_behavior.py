from pathlib import Path
from struct import pack
from types import SimpleNamespace
import zlib

import pytest

import app.adapters.mdict as mdict_module
from app.adapters.mdict import (
    MDictAdapter,
    MDictReadError,
    _LazyRecordFile,
    _HeadwordEntry,
    _decompress_zlib_limited,
    _discover_sidecars,
    _substitute_styles,
)


class _FakeRecords:
    def __init__(self, records: list[bytes]) -> None:
        self.records = records

    def record(self, index: int, *, max_output_bytes: int | None = None) -> bytes:
        body = self.records[index]
        if max_output_bytes is not None and len(body) > max_output_bytes:
            raise MDictReadError("fixture record exceeds its limit")
        return body


def _adapter(
    records: list[bytes],
    index: dict[str, list[int]],
    *,
    max_article_bytes: int = 1024 * 1024,
) -> MDictAdapter:
    adapter = object.__new__(MDictAdapter)
    adapter._dictionary_id = "fake-mdict"
    adapter._encoding = "utf-8"
    adapter._styles = {}
    adapter._max_article_bytes = max_article_bytes
    adapter._records = _FakeRecords(records)
    adapter._headwords = {
        word: _HeadwordEntry(display=word.title(), record_indexes=record_indexes)
        for word, record_indexes in index.items()
    }
    adapter._sorted_headwords = sorted(adapter._headwords)
    return adapter


def test_redirect_resolves_all_target_homographs_and_cycles_are_bounded():
    adapter = _adapter(
        [
            b"@@@LINK=target",
            b"<p>First homograph</p>",
            b"<p>Second homograph</p>",
            b"@@@LINK=cycle-two",
            b"@@@LINK=cycle-one",
        ],
        {
            "alias": [0],
            "target": [1, 2],
            "cycle-one": [3],
            "cycle-two": [4],
        },
    )

    article = adapter.lookup("ALIAS")

    assert article is not None
    assert article.html.count('class="mdict"') == 2
    assert "First homograph" in article.html
    assert "Second homograph" in article.html
    assert adapter.lookup("cycle-one") is None


def test_mdict_stylesheet_markers_close_the_previous_style():
    rendered = _substitute_styles(
        "`1`one`2`two",
        {"1": ("<b>", "</b>"), "2": ("<i>", "</i>")},
    )

    assert rendered == "<b>one</b><i>two</i>"


@pytest.mark.parametrize(
    ("compressed_size", "decompressed_size"),
    [(65, 8), (8, 65)],
)
def test_mdict_rejects_oversized_block_declarations_before_decompression(
    tmp_path: Path,
    compressed_size: int,
    decompressed_size: int,
):
    table = tmp_path / "record-table.bin"
    table.write_bytes(
        pack(
            ">IIIIII",
            1,
            1,
            8,
            compressed_size,
            compressed_size,
            decompressed_size,
        )
    )
    reader = SimpleNamespace(
        _fname=str(table),
        _record_block_offset=0,
        _num_entries=1,
        _number_width=4,
        _key_list=[(0, b"word")],
        _read_number=lambda source: int.from_bytes(source.read(4), "big"),
    )

    with pytest.raises(MDictReadError, match="block exceeds"):
        _LazyRecordFile(reader, cache_bytes=0, max_block_bytes=64)


def test_mdict_record_and_zlib_output_are_bounded_before_materialization():
    records = object.__new__(_LazyRecordFile)
    records.reader = SimpleNamespace(_key_list=[(0, b"first"), (65, b"second")])
    records._total_size = 65

    with pytest.raises(MDictReadError, match="output size"):
        records.record(0, max_output_bytes=64)
    with pytest.raises(MDictReadError, match="declared size"):
        _decompress_zlib_limited(zlib.compress(b"x" * 65), expected_size=64)


def test_mdict_combined_homographs_respect_the_article_bound():
    adapter = _adapter(
        [b"123456", b"abcdef"],
        {"large": [0, 1]},
        max_article_bytes=10,
    )

    with pytest.raises(MDictReadError, match="article exceeds"):
        adapter.lookup("large")


def test_mdict_sidecars_cannot_escape_the_dictionary_directory(tmp_path: Path):
    dictionary_directory = tmp_path / "dictionary"
    dictionary_directory.mkdir()
    main_path = dictionary_directory / "fixture.mdx"
    main_path.write_bytes(b"fixture")
    sidecar = dictionary_directory / "fixture.css"
    sidecar.write_text("body {}", encoding="utf-8")
    outside = tmp_path / "outside.css"
    outside.write_text("secret", encoding="utf-8")
    (dictionary_directory / "fixture-leak.css").symlink_to(outside)

    discovered = _discover_sidecars(main_path.resolve())

    assert discovered == {"fixture.css": sidecar.resolve()}


def test_mdict_volume_discovery_rejects_an_external_symlink(tmp_path: Path, monkeypatch):
    dictionary_directory = tmp_path / "dictionary"
    dictionary_directory.mkdir()
    main_path = dictionary_directory / "fixture.mdx"
    main_path.write_bytes(b"fixture")
    inside_volume = dictionary_directory / "fixture.1.mdd"
    inside_volume.write_bytes(b"inside")
    outside_volume = tmp_path / "outside.mdd"
    outside_volume.write_bytes(b"outside")
    (dictionary_directory / "fixture.mdd").symlink_to(outside_volume)
    adapter = object.__new__(MDictAdapter)
    adapter._mdd_readers = []
    adapter._mdd_resources = {}
    monkeypatch.setattr(mdict_module, "MDD", lambda value: Path(value))
    monkeypatch.setattr(
        mdict_module,
        "_LazyRecordFile",
        lambda reader, cache_bytes, max_block_bytes: SimpleNamespace(
            reader=reader,
            keys=[],
        ),
    )

    adapter._load_mdd_volumes(
        main_path.resolve(),
        cache_bytes=1024,
        max_block_bytes=1024,
    )

    assert len(adapter._mdd_readers) == 1
    assert adapter._mdd_readers[0].reader == inside_volume.resolve()
