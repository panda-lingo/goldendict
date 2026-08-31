"""Lock-protected copy-on-write dictionary catalog."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .adapters.base import DictionaryAdapter


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    generation: int
    adapters: tuple[DictionaryAdapter, ...]


class DictionaryCatalog:
    """Publishes complete immutable snapshots to concurrent lookups."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generation = 0
        self._by_id: dict[str, DictionaryAdapter] = {}

    def snapshot(self, dictionary_ids: list[str] | None = None) -> CatalogSnapshot:
        with self._lock:
            if dictionary_ids is None:
                adapters = tuple(self._by_id.values())
            else:
                adapters = tuple(
                    self._by_id[dictionary_id]
                    for dictionary_id in dictionary_ids
                    if dictionary_id in self._by_id
                )
            return CatalogSnapshot(generation=self._generation, adapters=adapters)

    def select(self, dictionary_ids: list[str]) -> tuple[CatalogSnapshot, list[str]]:
        with self._lock:
            missing = [dictionary_id for dictionary_id in dictionary_ids if dictionary_id not in self._by_id]
            adapters = tuple(
                self._by_id[dictionary_id]
                for dictionary_id in dictionary_ids
                if dictionary_id in self._by_id
            )
            return CatalogSnapshot(generation=self._generation, adapters=adapters), missing

    def replace_all(self, adapters: list[DictionaryAdapter]) -> tuple[DictionaryAdapter, ...]:
        replacement: dict[str, DictionaryAdapter] = {}
        for adapter in adapters:
            dictionary_id = adapter.metadata.dictionary_id
            if dictionary_id in replacement:
                raise ValueError(f"duplicate dictionary ID: {dictionary_id}")
            replacement[dictionary_id] = adapter
        with self._lock:
            previous = tuple(self._by_id.values())
            self._by_id = replacement
            self._generation += 1
            return previous
