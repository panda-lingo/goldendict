from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.adapters.mdict import MDictAdapter


@pytest.mark.integration
def test_real_mdx_mdd_fixture_lookup_redirects_and_resources():
    fixture = os.getenv("GOLDENDICT_TEST_MDX")
    if not fixture:
        pytest.skip("set GOLDENDICT_TEST_MDX to a real .mdx fixture")
    path = Path(fixture)
    if not path.is_file():
        pytest.skip(f"fixture is unavailable: {path}")

    adapter = MDictAdapter(path, cache_bytes=8 * 1024 * 1024)
    article = adapter.lookup("hello")

    assert adapter.metadata.word_count > 100_000
    assert article is not None
    assert "<div" in article.html
    assert "/api/v1/dictionaries/" in article.html
    assert 'data-gd-action="lookup"' in article.html
    assert 'data-gd-action="audio"' in article.html
    assert adapter.suggestions("hell", 10)

    css = adapter.resource(f"{path.stem}.css")
    assert css is not None
    assert css.media_type.startswith("text/css")
    assert b"/api/v1/dictionaries/" in css.body

    for script_name in (f"{path.stem}.js", f"{path.stem}-jquery.js"):
        script = adapter.resource(script_name)
        assert script is not None
        assert script.media_type.startswith("text/javascript")
        assert len(script.body) > 1_000

    nested_css = adapter.resource("css/dict.css")
    assert nested_css is not None
    assert nested_css.media_type.startswith("text/css")
    assert b"/api/v1/dictionaries/" in nested_css.body
    nested_image = adapter.resource("images/expand_icon.svg")
    assert nested_image is not None
    assert nested_image.media_type == "image/svg+xml"
    assert nested_image.body.lstrip().startswith(b"<?xml")
    nested_script = adapter.resource("scripts/full.min.js")
    assert nested_script is not None
    assert nested_script.media_type.startswith("text/javascript")
    assert len(nested_script.body) > 1_000_000

    same_path_adapter = MDictAdapter(path, cache_bytes=1024 * 1024)
    assert same_path_adapter.metadata.dictionary_id == adapter.metadata.dictionary_id
