"""Format-neutral dictionary application service."""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter_ns

from .adapters.base import DictionaryAdapter
from .adapters.native import (
    NativeDictionaryAdapter,
    NativeLookupResult,
    NativeWorkerClient,
    NativeWorkerError,
)
from .catalog import DictionaryCatalog
from .config import Settings
from .errors import bad_request, not_found
from .models import ArticleResponse, DictionaryInfo, LookupResponse, SuggestionsResponse
from .text import normalize_headword
from .transform import resource_base_url


logger = logging.getLogger(__name__)


class DictionaryService:
    def __init__(self, settings: Settings, catalog: DictionaryCatalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog or DictionaryCatalog()
        self.ready = False
        self.startup_errors: list[str] = []
        self._native_clients: list[NativeWorkerClient] = []

    def scan(self) -> None:
        """Start GoldenDict-ng and atomically publish its complete catalog."""

        adapters: list[DictionaryAdapter] = []
        errors: list[str] = []
        roots: list[Path] = []
        for root_value in self.settings.dictionary_roots:
            try:
                root = root_value.resolve(strict=True)
            except OSError:
                errors.append(f"dictionary root is unavailable: {root_value}")
                continue
            if not root.is_dir():
                errors.append(f"dictionary root is not a directory: {root_value}")
                continue
            if root not in roots:
                roots.append(root)

        native_client: NativeWorkerClient | None = None
        native_failed = not roots
        if roots:
            try:
                native_client = NativeWorkerClient(
                    self.settings.native_worker,
                    tuple(roots),
                    self.settings.native_index_dir,
                    startup_timeout_seconds=self.settings.native_startup_timeout_seconds,
                    request_timeout_seconds=self.settings.native_request_timeout_seconds,
                )
                for descriptor in native_client.dictionaries:
                    try:
                        main_path = descriptor.main_path.resolve(strict=True)
                        if not any(_is_within(main_path, root) for root in roots):
                            errors.append(
                                f"native worker returned out-of-root dictionary: {descriptor.main_path}"
                            )
                            native_failed = True
                            continue
                        adapters.append(
                            NativeDictionaryAdapter(
                                native_client,
                                descriptor,
                                max_resource_bytes=self.settings.max_resource_bytes,
                            )
                        )
                    except Exception as error:
                        native_failed = True
                        errors.append(
                            f"{descriptor.main_path.name}: native metadata: "
                            f"{type(error).__name__}: {error}"
                        )
            except Exception as error:
                errors.append(f"native worker: {type(error).__name__}: {error}")
                native_failed = True
                native_client = None

        try:
            retired = self.catalog.replace_all(adapters)
        except Exception:
            if native_client is not None:
                native_client.close()
            raise
        replacement_clients: list[NativeWorkerClient] = []
        if native_client is not None:
            replacement_clients.append(native_client)
        _close_adapters(retired)
        previous_clients, self._native_clients = self._native_clients, replacement_clients
        for previous_client in previous_clients:
            try:
                previous_client.close()
            except Exception:
                logger.exception("Failed to retire GoldenDict-ng native worker")
        self.startup_errors = errors
        self.ready = not native_failed

    def close(self) -> None:
        """Atomically empty the catalog and retire all published readers."""

        _close_adapters(self.catalog.replace_all([]))
        clients, self._native_clients = self._native_clients, []
        for client in clients:
            try:
                client.close()
            except Exception:
                logger.exception("Failed to close GoldenDict-ng native worker")

    def dictionaries(self) -> list[DictionaryInfo]:
        return [self.info(adapter) for adapter in self.catalog.snapshot().adapters]

    def lookup(
        self,
        word: str,
        dictionary_ids: list[str] | None = None,
    ) -> LookupResponse:
        started = perf_counter_ns()
        query = self._validate_query(word, field="word")
        adapters = self._selected_adapters(dictionary_ids)
        native_client = _shared_native_client(adapters)
        if native_client is not None:
            native_result = native_client.lookup_batch(
                query,
                [adapter.metadata.dictionary_id for adapter in adapters],
                self.settings.suggestion_limit,
            )
            articles = _native_articles(adapters, native_result)
            suggestions = _limit_suggestions(
                native_result.suggestions,
                self.settings.suggestion_limit,
            )
        else:
            # Kept only for protocol-level test doubles. Runtime catalogs are
            # constructed exclusively from NativeDictionaryAdapter instances.
            articles = []
            for adapter in adapters:
                article = adapter.lookup(query)
                if article is None:
                    continue
                articles.append(_article_response(adapter, article.html))
            suggestions = self._collect_suggestions(
                adapters,
                query,
                self.settings.suggestion_limit,
            )
        return LookupResponse(
            word=query,
            articles=articles,
            suggestions=suggestions,
            lookup_time_ms=_elapsed_ms(started),
        )

    def suggestions(
        self,
        prefix: str,
        dictionary_ids: list[str] | None,
        limit: int,
    ) -> SuggestionsResponse:
        started = perf_counter_ns()
        query = self._validate_query(prefix, field="prefix")
        adapters = self._selected_adapters(dictionary_ids)
        bounded_limit = min(max(limit, 1), 100)
        native_client = _shared_native_client(adapters)
        values = (
            _limit_suggestions(
                native_client.suggestions_batch(
                    query,
                    [adapter.metadata.dictionary_id for adapter in adapters],
                    bounded_limit,
                ),
                bounded_limit,
            )
            if native_client is not None
            else self._collect_suggestions(adapters, query, bounded_limit)
        )
        return SuggestionsResponse(
            prefix=query,
            suggestions=values,
            lookup_time_ms=_elapsed_ms(started),
        )

    def adapter(self, dictionary_id: str) -> DictionaryAdapter:
        snapshot = self.catalog.snapshot([dictionary_id])
        if not snapshot.adapters:
            raise not_found(
                "dictionaryNotFound",
                "The requested dictionary is not loaded.",
                dictionaryId=dictionary_id,
            )
        return snapshot.adapters[0]

    def info(self, adapter: DictionaryAdapter) -> DictionaryInfo:
        metadata = adapter.metadata
        base_url = resource_base_url(metadata.dictionary_id)
        return DictionaryInfo(
            id=metadata.dictionary_id,
            name=metadata.name,
            format=metadata.format,
            word_count=metadata.word_count,
            source_language=metadata.source_language,
            target_language=metadata.target_language,
            icon_url=(base_url + metadata.icon_resource_path if metadata.icon_resource_path else None),
            resource_base_url=base_url,
        )

    def _selected_adapters(self, dictionary_ids: list[str] | None) -> tuple[DictionaryAdapter, ...]:
        if dictionary_ids:
            dictionary_ids = list(dict.fromkeys(dictionary_ids))
            snapshot, missing = self.catalog.select(dictionary_ids)
            if missing:
                raise not_found(
                    "dictionaryNotFound",
                    "One or more requested dictionaries are not loaded.",
                    dictionaryIds=missing,
                )
            return snapshot.adapters
        return self.catalog.snapshot().adapters

    def _validate_query(self, value: str, *, field: str) -> str:
        query = value.strip()
        if not query:
            raise bad_request("invalidQuery", f"{field} must not be blank.", field=field)
        if len(query) > self.settings.max_query_length:
            raise bad_request(
                "queryTooLong",
                f"{field} exceeds the configured character limit.",
                field=field,
                maxLength=self.settings.max_query_length,
            )
        return query

    @staticmethod
    def _collect_suggestions(
        adapters: tuple[DictionaryAdapter, ...],
        prefix: str,
        limit: int,
    ) -> list[str]:
        by_normalized: dict[str, str] = {}
        for adapter in adapters:
            for suggestion in adapter.suggestions(prefix, limit):
                normalized = normalize_headword(suggestion)
                if normalized:
                    by_normalized.setdefault(normalized, suggestion)
        return [by_normalized[key] for key in sorted(by_normalized)[:limit]]


def _shared_native_client(
    adapters: tuple[DictionaryAdapter, ...],
) -> NativeWorkerClient | None:
    if not adapters or not isinstance(adapters[0], NativeDictionaryAdapter):
        return None
    client = adapters[0].client
    if any(
        not isinstance(adapter, NativeDictionaryAdapter) or adapter.client is not client
        for adapter in adapters
    ):
        return None
    return client


def _native_articles(
    adapters: tuple[DictionaryAdapter, ...],
    result: NativeLookupResult,
) -> list[ArticleResponse]:
    selected = {adapter.metadata.dictionary_id: adapter for adapter in adapters}
    html_by_id: dict[str, str] = {}
    for article in result.articles:
        if article.dictionary_id not in selected or article.dictionary_id in html_by_id:
            raise NativeWorkerError("native lookup returned an unexpected dictionary article")
        html_by_id[article.dictionary_id] = article.html
    return [
        _article_response(adapter, html_by_id[adapter.metadata.dictionary_id])
        for adapter in adapters
        if adapter.metadata.dictionary_id in html_by_id
    ]


def _article_response(adapter: DictionaryAdapter, html: str) -> ArticleResponse:
    metadata = adapter.metadata
    base_url = resource_base_url(metadata.dictionary_id)
    return ArticleResponse(
        dictionary_id=metadata.dictionary_id,
        dictionary_name=metadata.name,
        format=metadata.format,
        html=html,
        source_language=metadata.source_language,
        target_language=metadata.target_language,
        icon_url=(
            base_url + metadata.icon_resource_path
            if metadata.icon_resource_path
            else None
        ),
        resource_base_url=base_url,
    )


def _limit_suggestions(values: tuple[str, ...], limit: int) -> list[str]:
    by_normalized: dict[str, str] = {}
    for value in values:
        normalized = normalize_headword(value)
        if normalized:
            by_normalized.setdefault(normalized, value)
    return [by_normalized[key] for key in sorted(by_normalized)[:limit]]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _elapsed_ms(started_ns: int) -> int:
    return max(0, (perf_counter_ns() - started_ns) // 1_000_000)


def _close_adapters(adapters: tuple[DictionaryAdapter, ...]) -> None:
    for adapter in adapters:
        try:
            adapter.close()
        except Exception:
            # Catalog publication already succeeded; cleanup is best-effort and
            # adapters are required to own no persistent shared file handles.
            logger.exception(
                "Failed to retire dictionary adapter %s",
                adapter.metadata.dictionary_id,
            )
