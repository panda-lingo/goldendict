from pathlib import Path

import pytest

from app.adapters import dsl, mdict, stardict
from app.adapters.factory import (
    ReaderRegistration,
    create_adapter,
    is_dictionary_main_file,
    register_reader,
)


def test_reader_registry_can_adopt_a_future_format_without_route_changes():
    registration = ReaderRegistration("future-fixture", (".future-dict",), lambda path, name, options: None)
    register_reader(registration)

    assert is_dictionary_main_file(Path("example.future-dict")) is True


@pytest.mark.parametrize(
    ("filename", "module", "class_name"),
    [
        ("fixture.dsl", dsl, "DSLAdapter"),
        ("fixture.ifo", stardict, "StarDictAdapter"),
    ],
)
def test_factory_forwards_the_resource_limit(
    tmp_path: Path,
    monkeypatch,
    filename: str,
    module,
    class_name: str,
):
    path = tmp_path / filename
    path.touch()
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_adapter(adapter_path, *, name=None, max_resource_bytes):
        captured.update(
            path=adapter_path,
            name=name,
            max_resource_bytes=max_resource_bytes,
        )
        return sentinel

    monkeypatch.setattr(module, class_name, fake_adapter)

    created = create_adapter(path, name="Named", max_resource_bytes=321)

    assert created is sentinel
    assert captured == {
        "path": path,
        "name": "Named",
        "max_resource_bytes": 321,
    }


def test_factory_forwards_all_mdict_memory_limits(tmp_path: Path, monkeypatch):
    path = tmp_path / "fixture.mdx"
    path.touch()
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_adapter(
        adapter_path,
        *,
        name=None,
        cache_bytes,
        max_block_bytes,
        max_article_bytes,
        max_resource_bytes,
    ):
        captured.update(
            path=adapter_path,
            name=name,
            cache_bytes=cache_bytes,
            max_block_bytes=max_block_bytes,
            max_article_bytes=max_article_bytes,
            max_resource_bytes=max_resource_bytes,
        )
        return sentinel

    monkeypatch.setattr(mdict, "MDictAdapter", fake_adapter)

    created = create_adapter(
        path,
        name="Named",
        mdict_cache_bytes=11,
        mdict_max_block_bytes=22,
        mdict_max_article_bytes=33,
        max_resource_bytes=44,
    )

    assert created is sentinel
    assert captured == {
        "path": path,
        "name": "Named",
        "cache_bytes": 11,
        "max_block_bytes": 22,
        "max_article_bytes": 33,
        "max_resource_bytes": 44,
    }
