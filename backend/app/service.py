"""Format-neutral dictionary application service."""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter_ns

from .adapters.base import DictionaryAdapter, UnsupportedDictionaryFormat
from .adapters.factory import create_adapter, is_dictionary_main_file
from .adapters.native import NativeDictionaryAdapter, NativeWorkerClient
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
        """Build all configured readers, then publish them in one catalog swap."""

        adapters: list[DictionaryAdapter] = []
        errors: list[str] = []
        seen: set[Path] = set()
        roots: list[Path] = []
        candidates: list[Path] = []
        native_failed = False
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
            for candidate in sorted(root.rglob("*")):
                if not candidate.is_file() or not is_dictionary_main_file(candidate):
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if resolved in seen or not _is_within(resolved, root):
                        continue
                    seen.add(resolved)
                    candidates.append(resolved)
                except Exception as error:  # one corrupt dictionary must not hide healthy ones
                    errors.append(f"{candidate.name}: {type(error).__name__}: {error}")

        native_client: NativeWorkerClient | None = None
        native_by_path: dict[Path, NativeDictionaryAdapter] = {}
        if self.settings.native_required and self.settings.native_worker is None:
            errors.append(
                "native worker is required but GOLDENDICT_NATIVE_WORKER is not configured"
            )
            native_failed = True
        if self.settings.native_worker is not None and roots:
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
                        if main_path not in seen or not any(
                            _is_within(main_path, root) for root in roots
                        ):
                            errors.append(
                                f"native worker ignored out-of-scan dictionary: {descriptor.main_path}"
                            )
                            native_failed = True
                            continue
                        if main_path in native_by_path:
                            errors.append(f"native worker returned duplicate path: {main_path}")
                            native_failed = True
                            continue
                        native_by_path[main_path] = NativeDictionaryAdapter(
                            native_client,
                            descriptor,
                            max_resource_bytes=self.settings.max_resource_bytes,
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
        elif self.settings.native_worker is not None and not roots:
            native_failed = True

        if self.settings.native_required:
            missing_native = [
                path
                for path in candidates
                if (
                    path.suffix.casefold() in {".mdx", ".ifo", ".dsl"}
                    or path.name.casefold().endswith(".dsl.dz")
                )
                and path not in native_by_path
            ]
            for path in missing_native:
                errors.append(f"{path.name}: required native dictionary was not published")
            native_failed = native_failed or bool(missing_native)

        for candidate in candidates:
            native_adapter = native_by_path.get(candidate)
            if native_adapter is not None:
                adapters.append(native_adapter)
                continue
            try:
                adapters.append(self._make_adapter(candidate))
            except Exception as error:  # one corrupt dictionary must not hide healthy ones
                errors.append(f"{candidate.name}: {type(error).__name__}: {error}")

        try:
            retired = self.catalog.replace_all(adapters)
        except Exception:
            if native_client is not None:
                native_client.close()
            raise
        replacement_clients: list[NativeWorkerClient] = []
        if native_client is not None:
            if native_by_path:
                replacement_clients.append(native_client)
            else:
                native_client.close()
        _close_adapters(retired)
        previous_clients, self._native_clients = self._native_clients, replacement_clients
        for previous_client in previous_clients:
            try:
                previous_client.close()
            except Exception:
                logger.exception("Failed to retire GoldenDict-ng native worker")
        self.startup_errors = errors
        self.ready = not (self.settings.native_required and native_failed)

    def load(self, path_value: str, name: str | None = None) -> DictionaryInfo:
        path = self.resolve_configured_path(path_value)
        if not is_dictionary_main_file(path):
            raise bad_request(
                "unsupportedDictionaryFormat",
                "The supplied path is not a supported dictionary main file.",
                filename=path.name,
            )
        try:
            adapter = self._make_adapter(path, name=name)
        except UnsupportedDictionaryFormat as error:
            raise bad_request("unsupportedDictionaryFormat", str(error), filename=path.name) from error
        except Exception as error:
            raise bad_request(
                "dictionaryLoadFailed",
                "The dictionary could not be loaded.",
                filename=path.name,
                reason=str(error),
            ) from error
        retired = self.catalog.upsert(adapter)
        if retired is not None and retired is not adapter:
            _close_adapters((retired,))
        return self.info(adapter)

    def unload(self, dictionary_id: str) -> None:
        retired = self.catalog.unload(dictionary_id)
        if retired is None:
            raise not_found(
                "dictionaryNotFound",
                "The requested dictionary is not loaded.",
                dictionaryId=dictionary_id,
            )
        _close_adapters((retired,))

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
        articles: list[ArticleResponse] = []
        for adapter in adapters:
            article = adapter.lookup(query)
            if article is None:
                continue
            metadata = adapter.metadata
            base_url = resource_base_url(metadata.dictionary_id)
            articles.append(
                ArticleResponse(
                    dictionary_id=metadata.dictionary_id,
                    dictionary_name=metadata.name,
                    format=metadata.format,
                    html=article.html,
                    source_language=metadata.source_language,
                    target_language=metadata.target_language,
                    icon_url=(base_url + metadata.icon_resource_path if metadata.icon_resource_path else None),
                    resource_base_url=base_url,
                )
            )
        suggestions = self._collect_suggestions(adapters, query, self.settings.suggestion_limit)
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
        return SuggestionsResponse(
            prefix=query,
            suggestions=self._collect_suggestions(adapters, query, bounded_limit),
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

    def resolve_configured_path(self, path_value: str) -> Path:
        supplied = Path(path_value).expanduser()
        candidates: list[Path] = []
        if supplied.is_absolute():
            try:
                candidates.append(supplied.resolve(strict=True))
            except OSError as error:
                raise not_found("dictionaryFileNotFound", "The dictionary file does not exist.") from error
        else:
            for root_value in self.settings.dictionary_roots:
                try:
                    candidate = (root_value / supplied).resolve(strict=True)
                except OSError:
                    continue
                if candidate not in candidates:
                    candidates.append(candidate)
        allowed_roots = []
        for root_value in self.settings.dictionary_roots:
            try:
                allowed_roots.append(root_value.resolve(strict=True))
            except OSError:
                continue
        safe = [
            candidate
            for candidate in candidates
            if candidate.is_file() and any(_is_within(candidate, root) for root in allowed_roots)
        ]
        if not safe:
            raise not_found(
                "dictionaryFileNotFound",
                "The dictionary file was not found beneath a configured dictionary root.",
            )
        if len(safe) > 1:
            raise bad_request(
                "ambiguousDictionaryPath",
                "The relative path exists beneath more than one configured dictionary root.",
            )
        return safe[0]

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

    def _make_adapter(self, path: Path, name: str | None = None) -> DictionaryAdapter:
        return create_adapter(
            path,
            name=name,
            mdict_cache_bytes=self.settings.mdict_cache_bytes,
            mdict_max_block_bytes=self.settings.mdict_max_block_bytes,
            mdict_max_article_bytes=self.settings.mdict_max_article_bytes,
            max_resource_bytes=self.settings.max_resource_bytes,
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
