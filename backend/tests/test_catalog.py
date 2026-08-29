from pathlib import Path

from app.catalog import DictionaryCatalog

from conftest import FakeAdapter


def test_catalog_swaps_complete_snapshots_and_reports_superseded_adapter(tmp_path: Path):
    catalog = DictionaryCatalog()
    first = FakeAdapter(tmp_path / "first.mdx", "first")
    second = FakeAdapter(tmp_path / "second.mdx", "second")

    assert catalog.replace_all([first]) == ()
    before = catalog.snapshot()
    retired = catalog.replace_all([second])
    after = catalog.snapshot()

    assert before.adapters == (first,)
    assert after.adapters == (second,)
    assert after.generation == before.generation + 1
    assert retired == (first,)


def test_catalog_select_is_atomic_and_preserves_requested_order(tmp_path: Path):
    catalog = DictionaryCatalog()
    first = FakeAdapter(tmp_path / "first.mdx", "first")
    second = FakeAdapter(tmp_path / "second.mdx", "second")
    catalog.replace_all([first, second])

    snapshot, missing = catalog.select(["second", "missing", "first"])

    assert snapshot.adapters == (second, first)
    assert missing == ["missing"]
