from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.base import (
    DictionaryAdapter,
    DictionaryArticle,
    DictionaryMetadata,
    DictionaryResource,
)
from app.config import Settings
from app.transform import etag_for


class FakeAdapter(DictionaryAdapter):
    def __init__(self, main_path: Path, dictionary_id: str = "fake-dictionary") -> None:
        self.metadata = DictionaryMetadata(
            dictionary_id=dictionary_id,
            name="Fake Dictionary",
            format="fake",
            word_count=2,
            main_path=main_path,
            source_language="en",
            target_language="fr",
            icon_resource_path="fake.png",
        )
        self.closed = False

    def lookup(self, word: str) -> DictionaryArticle | None:
        if word.casefold() != "hello":
            return None
        return DictionaryArticle(html="<p>Hello definition</p>", headword="Hello")

    def suggestions(self, prefix: str, limit: int) -> list[str]:
        return [word for word in ("Hello", "Help") if word.casefold().startswith(prefix.casefold())][:limit]

    def resource(self, resource_path: str) -> DictionaryResource | None:
        if resource_path.casefold() != "fake.png":
            return None
        body = b"fake-png"
        return DictionaryResource(body=body, media_type="image/png", etag=etag_for(body))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def dictionary_root(tmp_path: Path) -> Path:
    root = tmp_path / "dictionaries"
    root.mkdir()
    return root


@pytest.fixture
def settings(dictionary_root: Path) -> Settings:
    return Settings(dictionary_roots=(dictionary_root,), startup_scan=False)
