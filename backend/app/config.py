"""Environment-backed service configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _split_paths(value: str) -> tuple[Path, ...]:
    return tuple(Path(part).expanduser() for part in value.split(os.pathsep) if part.strip())


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    dictionary_roots: tuple[Path, ...]
    max_resource_bytes: int = 128 * 1024 * 1024
    max_query_length: int = 512
    suggestion_limit: int = 20
    cors_origins: tuple[str, ...] = ("*",)
    startup_scan: bool = True
    runtime_catalog_mutations: bool = False
    mdict_cache_bytes: int = 32 * 1024 * 1024
    mdict_max_block_bytes: int = 128 * 1024 * 1024
    mdict_max_article_bytes: int = 32 * 1024 * 1024
    native_worker: Path | None = None
    native_index_dir: Path = Path("./.goldendict-native-indices")
    native_startup_timeout_seconds: float = 600
    native_request_timeout_seconds: float = 45
    native_required: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        roots = _split_paths(os.getenv("GOLDENDICT_DICTIONARY_ROOTS", "./dictionaries"))
        native_worker_value = os.getenv("GOLDENDICT_NATIVE_WORKER", "").strip()
        return cls(
            dictionary_roots=roots,
            max_resource_bytes=int(os.getenv("GOLDENDICT_MAX_RESOURCE_BYTES", str(128 * 1024 * 1024))),
            max_query_length=int(os.getenv("GOLDENDICT_MAX_QUERY_LENGTH", "512")),
            suggestion_limit=int(os.getenv("GOLDENDICT_SUGGESTION_LIMIT", "20")),
            cors_origins=_split_csv(os.getenv("GOLDENDICT_CORS_ORIGINS", "*")),
            startup_scan=_env_bool("GOLDENDICT_STARTUP_SCAN", True),
            runtime_catalog_mutations=_env_bool(
                "GOLDENDICT_RUNTIME_CATALOG_MUTATIONS", False
            ),
            mdict_cache_bytes=int(os.getenv("GOLDENDICT_MDICT_CACHE_BYTES", str(32 * 1024 * 1024))),
            mdict_max_block_bytes=int(
                os.getenv("GOLDENDICT_MDICT_MAX_BLOCK_BYTES", str(128 * 1024 * 1024))
            ),
            mdict_max_article_bytes=int(
                os.getenv("GOLDENDICT_MDICT_MAX_ARTICLE_BYTES", str(32 * 1024 * 1024))
            ),
            native_worker=Path(native_worker_value).expanduser() if native_worker_value else None,
            native_index_dir=Path(
                os.getenv("GOLDENDICT_NATIVE_INDEX_DIR", "./.goldendict-native-indices")
            ).expanduser(),
            native_startup_timeout_seconds=float(
                os.getenv("GOLDENDICT_NATIVE_STARTUP_TIMEOUT_SECONDS", "600")
            ),
            native_request_timeout_seconds=float(
                os.getenv("GOLDENDICT_NATIVE_REQUEST_TIMEOUT_SECONDS", "45")
            ),
            native_required=_env_bool("GOLDENDICT_NATIVE_REQUIRED", False),
        )

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return self.dictionary_roots
