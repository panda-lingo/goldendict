"""Format-neutral boundary around dictionaries owned by GoldenDict-ng."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Final


MAX_SUGGESTION_LIMIT: Final = 100


@dataclass(frozen=True, slots=True)
class DictionaryMetadata:
    """Stable public metadata for one loaded dictionary."""

    dictionary_id: str
    name: str
    format: str
    word_count: int
    main_path: Path
    source_language: str | None = None
    target_language: str | None = None
    icon_resource_path: str | None = None


@dataclass(frozen=True, slots=True)
class DictionaryArticle:
    """One browser-ready article fragment returned by a reader."""

    html: str
    headword: str


@dataclass(frozen=True, slots=True)
class DictionaryResource:
    """A resource body and representation metadata."""

    body: bytes
    media_type: str
    etag: str
    # Keep the representation cacheable, but force an ETag revalidation so a
    # locally modified dictionary bundle never leaves stale CSS/media at the
    # same stable URL after the service restarts.
    cache_control: str = "public, max-age=0, must-revalidate"


class DictionaryAdapter(ABC):
    """Immutable, thread-safe dictionary instance held by the catalog.

    The runtime implementation delegates to the shared native worker. Calls can
    happen from multiple gateway threads, and ``close()`` is called just after
    a copy-on-write catalog swap, so it must remain safe while an older request
    snapshot finishes a lookup.
    """

    metadata: DictionaryMetadata

    @abstractmethod
    def lookup(self, word: str) -> DictionaryArticle | None:
        """Return all homographs for an exact, Unicode-casefolded headword."""

    @abstractmethod
    def suggestions(self, prefix: str, limit: int) -> list[str]:
        """Return at most ``limit`` distinct prefix matches in display form."""

    @abstractmethod
    def resource(self, resource_path: str) -> DictionaryResource | None:
        """Return a normalized companion resource, if it exists."""

    def close(self) -> None:
        """Release discardable caches after an atomic catalog swap."""
