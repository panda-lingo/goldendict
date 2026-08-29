from __future__ import annotations

import gzip
from pathlib import Path

from app.adapters.dsl import DSLAdapter, DslAdapter


def test_dsl_indexes_utf16_aliases_renders_tags_and_serves_safe_resources(
    tmp_path: Path,
) -> None:
    dictionary = tmp_path / "sample.dsl"
    dictionary.write_bytes(
        (
            '#NAME "Example DSL"\n'
            '#INDEX_LANGUAGE "English"\n'
            '#CONTENTS_LANGUAGE "French"\n'
            "Color\n"
            "colour\n"
            "\t[m1][b]~[/b] [i]shade[/i] \\[b\\] "
            "[ref]paint[/ref] [s]images/pic.png[/s][/m1]\n"
            "\n"
            "Tone\n"
            "\t[m1]sound[/m1]\n"
        ).encode("utf-16")
    )
    resource_root = tmp_path / "sample.files"
    (resource_root / "images").mkdir(parents=True)
    (resource_root / "images" / "pic.png").write_bytes(b"not-a-real-png")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (resource_root / "escape.txt").symlink_to(outside)

    adapter = DSLAdapter(dictionary, dictionary_id="fixture-dsl")

    assert isinstance(adapter, DslAdapter)
    assert adapter.metadata.name == "Example DSL"
    assert adapter.metadata.source_language == "English"
    assert adapter.metadata.target_language == "French"
    assert adapter.metadata.word_count == 3

    article = adapter.lookup("COLOUR")
    assert article is not None
    assert article.headword == "colour"
    assert '<div class="dsl_article">' in article.html
    assert '<div class="dsl_m1">' in article.html
    assert '<b class="dsl_b">colour</b>' in article.html
    assert '<i class="dsl_i">shade</i>' in article.html
    assert "[b]" in article.html
    assert 'data-gd-action="lookup"' in article.html
    assert 'data-gd-word="paint"' in article.html
    assert 'href="#gdlookup=paint"' in article.html
    assert 'src="/api/v1/dictionaries/fixture-dsl/resources/images/pic.png"' in article.html
    assert adapter.lookup("missing") is None
    assert adapter.suggestions("col", 10) == ["Color", "colour"]
    assert adapter.suggestions("", 1) == []
    assert adapter.suggestions("col", 0) == []

    resource = adapter.resource("images/pic.png")
    assert resource is not None
    assert resource.body == b"not-a-real-png"
    assert resource.media_type == "image/png"
    assert resource.etag.startswith('"') and resource.etag.endswith('"')
    assert adapter.resource("../secret.txt") is None
    assert adapter.resource("%2e%2e/secret.txt") is None
    assert adapter.resource("escape.txt") is None


def test_dsl_dz_accepts_utf8_bom_and_substitutes_the_exact_headword(
    tmp_path: Path,
) -> None:
    dictionary = tmp_path / "packed.dsl.dz"
    source = '#NAME "Packed"\nCafé\n\t[m1][u]~[/u][/m1]\n'.encode("utf-8-sig")
    dictionary.write_bytes(gzip.compress(source, mtime=0))

    adapter = DSLAdapter(dictionary, dictionary_id="packed")
    article = adapter.lookup("CAFÉ")

    assert adapter.metadata.name == "Packed"
    assert article is not None
    assert article.headword == "Café"
    assert '<span class="dsl_u">Café</span>' in article.html
    assert adapter.suggestions("caf", 1000) == ["Café"]
