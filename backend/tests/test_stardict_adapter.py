from __future__ import annotations

import gzip
from pathlib import Path

from app.adapters.stardict import StarDictAdapter, StardictAdapter


def _write_stardict(
    root: Path,
    records: list[tuple[str, bytes]],
    *,
    same_type_sequence: str | None,
    offset_bits: int = 32,
    gzip_index: bool = False,
    gzip_dictionary: bool = False,
    synonyms: list[tuple[str, int]] | None = None,
) -> Path:
    stem = root / "fixture"
    dictionary_data = bytearray()
    index_data = bytearray()
    width = offset_bits // 8
    for word, record in records:
        offset = len(dictionary_data)
        dictionary_data.extend(record)
        index_data.extend(word.encode("utf-8"))
        index_data.append(0)
        index_data.extend(offset.to_bytes(width, "big"))
        index_data.extend(len(record).to_bytes(4, "big"))

    idx_path = stem.with_suffix(".idx.gz" if gzip_index else ".idx")
    idx_body = bytes(index_data)
    idx_path.write_bytes(gzip.compress(idx_body, mtime=0) if gzip_index else idx_body)
    dict_path = stem.with_suffix(".dict.dz" if gzip_dictionary else ".dict")
    dict_body = bytes(dictionary_data)
    dict_path.write_bytes(
        gzip.compress(dict_body, mtime=0) if gzip_dictionary else dict_body
    )

    if synonyms:
        synonym_data = bytearray()
        for synonym, entry_number in synonyms:
            synonym_data.extend(synonym.encode("utf-8"))
            synonym_data.append(0)
            synonym_data.extend(entry_number.to_bytes(4, "big"))
        stem.with_suffix(".syn").write_bytes(synonym_data)

    lines = [
        "StarDict's dict ifo file",
        "version=3.0.0",
        "bookname=Fixture StarDict",
        f"wordcount={len(records)}",
        f"idxfilesize={len(idx_body)}",
        f"idxoffsetbits={offset_bits}",
    ]
    if same_type_sequence is not None:
        lines.append(f"sametypesequence={same_type_sequence}")
    if synonyms:
        lines.append(f"synwordcount={len(synonyms)}")
    ifo_path = stem.with_suffix(".ifo")
    ifo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ifo_path


def test_stardict_same_type_sequence_synonyms_html_and_resources(tmp_path: Path) -> None:
    html_field = (
        '<link href="style.css"><p><img src="img/p.png">'
        '<a href="bword://world">World</a>'
        '<a href="earth">Earth</a></p>'
    ).encode("utf-8")
    records = [
        ("hello", html_field + b"\x00" + b"Plain\nmeaning"),
        ("world", b"<b>World</b>\x00A planet"),
    ]
    ifo_path = _write_stardict(
        tmp_path,
        records,
        same_type_sequence="hm",
        synonyms=[("hi", 0)],
    )
    resource_root = tmp_path / "res" / "img"
    resource_root.mkdir(parents=True)
    (resource_root / "p.png").write_bytes(b"png-body")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (tmp_path / "res" / "escape.bin").symlink_to(outside)

    adapter = StarDictAdapter(ifo_path, dictionary_id="fixture-star")

    assert isinstance(adapter, StardictAdapter)
    assert adapter.metadata.name == "Fixture StarDict"
    assert adapter.metadata.format == "stardict"
    assert adapter.metadata.word_count == 3

    article = adapter.lookup("HELLO")
    assert article is not None
    assert article.headword == "hello"
    assert '<div class="sdct_h">' in article.html
    assert 'src="/api/v1/dictionaries/fixture-star/resources/img/p.png"' in article.html
    assert 'href="/api/v1/dictionaries/fixture-star/resources/style.css"' in article.html
    assert 'data-gd-word="world"' in article.html
    assert 'data-gd-word="earth"' in article.html
    assert "/resources/earth" not in article.html
    assert '<div class="sdct_m">Plain<br/>meaning</div>' in article.html

    alias = adapter.lookup("HI")
    assert alias is not None
    assert alias.headword == "hi"
    assert "Plain<br/>meaning" in alias.html
    assert adapter.suggestions("h", 10) == ["hello", "hi"]
    assert adapter.lookup("unknown") is None

    resource = adapter.resource("img/p.png")
    assert resource is not None
    assert resource.body == b"png-body"
    assert resource.media_type == "image/png"
    assert adapter.resource("../outside.bin") is None
    assert adapter.resource("%2e%2e/outside.bin") is None
    assert adapter.resource("escape.bin") is None


def test_stardict_64_bit_gzip_and_per_field_type_markers(tmp_path: Path) -> None:
    record = (
        b"h"
        + b'<img src="art.png">'
        + b"\x00"
        + b"g"
        + b'<span foreground="#ff0000"><b>bold</b></span>'
        + b"\x00"
        + b"t"
        + b"/word/"
        + b"\x00"
        + b"P"
        + (3).to_bytes(4, "big")
        + b"PNG"
    )
    ifo_path = _write_stardict(
        tmp_path,
        [("word", record)],
        same_type_sequence=None,
        offset_bits=64,
        gzip_index=True,
        gzip_dictionary=True,
    )

    adapter = StarDictAdapter(ifo_path, dictionary_id="compressed")
    article = adapter.lookup("Word")

    assert article is not None
    assert '/api/v1/dictionaries/compressed/resources/art.png' in article.html
    assert '<div class="sdct_g"><span style="color:#ff0000"><b>bold</b></span></div>' in article.html
    assert '<div class="sdct_t">/word/</div>' in article.html
    assert "PNG" not in article.html
