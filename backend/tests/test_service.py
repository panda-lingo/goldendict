from pathlib import Path

import pytest

from app.errors import ServiceError
from app.service import DictionaryService

from conftest import FakeAdapter


def test_lookup_combines_format_neutral_articles_and_suggestions(settings, dictionary_root: Path):
    service = DictionaryService(settings)
    adapter = FakeAdapter(dictionary_root / "fixture.mdx")
    service.catalog.replace_all([adapter])

    response = service.lookup(" hello ")

    assert response.word == "hello"
    assert response.articles[0].dictionary_id == "fake-dictionary"
    assert response.articles[0].resource_base_url.endswith("/fake-dictionary/resources/")
    assert response.suggestions == ["Hello"]


def test_unknown_selected_dictionary_is_structured_not_found(settings):
    service = DictionaryService(settings)

    with pytest.raises(ServiceError) as captured:
        service.lookup("hello", ["missing"])

    assert captured.value.status_code == 404
    assert captured.value.details == {"dictionaryIds": ["missing"]}
