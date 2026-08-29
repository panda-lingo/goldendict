from pathlib import Path

import pytest

from app.errors import ServiceError
from app.service import DictionaryService

from conftest import FakeAdapter


def test_load_is_confined_to_real_configured_root(settings, dictionary_root: Path, tmp_path: Path, monkeypatch):
    dictionary = dictionary_root / "fixture.mdx"
    dictionary.write_bytes(b"fixture")
    outside = tmp_path / "outside.mdx"
    outside.write_bytes(b"outside")
    escaped = dictionary_root / "escaped.mdx"
    escaped.symlink_to(outside)
    service = DictionaryService(settings)
    adapter = FakeAdapter(dictionary)
    monkeypatch.setattr(service, "_make_adapter", lambda path, name=None: adapter)

    loaded = service.load("fixture.mdx", "Custom")

    assert loaded.id == "fake-dictionary"
    with pytest.raises(ServiceError) as captured:
        service.load(str(outside))
    assert captured.value.code == "dictionaryFileNotFound"
    with pytest.raises(ServiceError) as captured:
        service.load("escaped.mdx")
    assert captured.value.code == "dictionaryFileNotFound"


def test_lookup_combines_format_neutral_articles_and_suggestions(settings, dictionary_root: Path):
    service = DictionaryService(settings)
    adapter = FakeAdapter(dictionary_root / "fixture.mdx")
    service.catalog.replace_all([adapter])

    response = service.lookup(" hello ")

    assert response.word == "hello"
    assert response.articles[0].dictionary_id == "fake-dictionary"
    assert response.articles[0].resource_base_url.endswith("/fake-dictionary/resources/")
    assert response.suggestions == ["Hello"]


def test_unload_drops_reader_but_never_deletes_source(settings, dictionary_root: Path):
    source = dictionary_root / "fixture.mdx"
    source.write_bytes(b"source remains")
    service = DictionaryService(settings)
    adapter = FakeAdapter(source)
    service.catalog.replace_all([adapter])

    service.unload("fake-dictionary")

    assert adapter.closed is True
    assert source.read_bytes() == b"source remains"
    assert service.dictionaries() == []


def test_load_retires_the_superseded_reader(settings, dictionary_root: Path, monkeypatch):
    source = dictionary_root / "fixture.mdx"
    source.write_bytes(b"source")
    service = DictionaryService(settings)
    previous = FakeAdapter(source)
    replacement = FakeAdapter(source)
    service.catalog.replace_all([previous])
    monkeypatch.setattr(service, "_make_adapter", lambda path, name=None: replacement)

    service.load("fixture.mdx")

    assert previous.closed is True
    assert replacement.closed is False


def test_unknown_selected_dictionary_is_structured_not_found(settings):
    service = DictionaryService(settings)

    with pytest.raises(ServiceError) as captured:
        service.lookup("hello", ["missing"])

    assert captured.value.status_code == 404
    assert captured.value.details == {"dictionaryIds": ["missing"]}
