"""Extensible format registry and adapter construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable

from .base import DictionaryAdapter, UnsupportedDictionaryFormat


@dataclass(frozen=True, slots=True)
class FactoryOptions:
    mdict_cache_bytes: int
    mdict_max_block_bytes: int
    mdict_max_article_bytes: int
    max_resource_bytes: int


AdapterBuilder = Callable[[Path, str | None, FactoryOptions], DictionaryAdapter]


@dataclass(frozen=True, slots=True)
class ReaderRegistration:
    format_name: str
    suffixes: tuple[str, ...]
    build: AdapterBuilder

    def owns(self, path: Path) -> bool:
        lowered = path.name.casefold()
        return any(lowered.endswith(suffix.casefold()) for suffix in self.suffixes)


_registry_lock = RLock()
_registry: list[ReaderRegistration] = []


def register_reader(registration: ReaderRegistration, *, replace: bool = False) -> None:
    """Register a format without changing routes, catalog, or service code."""

    with _registry_lock:
        existing = next(
            (index for index, item in enumerate(_registry) if item.format_name == registration.format_name),
            None,
        )
        if existing is not None:
            if not replace:
                raise ValueError(f"reader is already registered: {registration.format_name}")
            _registry[existing] = registration
        else:
            _registry.append(registration)


def registered_readers() -> tuple[ReaderRegistration, ...]:
    with _registry_lock:
        return tuple(_registry)


def is_dictionary_main_file(path: Path) -> bool:
    return any(registration.owns(path) for registration in registered_readers())


def create_adapter(
    path: Path,
    *,
    name: str | None = None,
    mdict_cache_bytes: int = 32 * 1024 * 1024,
    mdict_max_block_bytes: int = 128 * 1024 * 1024,
    mdict_max_article_bytes: int = 32 * 1024 * 1024,
    max_resource_bytes: int = 128 * 1024 * 1024,
) -> DictionaryAdapter:
    options = FactoryOptions(
        mdict_cache_bytes=mdict_cache_bytes,
        mdict_max_block_bytes=mdict_max_block_bytes,
        mdict_max_article_bytes=mdict_max_article_bytes,
        max_resource_bytes=max_resource_bytes,
    )
    for registration in registered_readers():
        if registration.owns(path):
            return registration.build(path, name, options)
    raise UnsupportedDictionaryFormat(f"unsupported dictionary format: {path.name}")


def _build_mdict(path: Path, name: str | None, options: FactoryOptions) -> DictionaryAdapter:
    from .mdict import MDictAdapter

    return MDictAdapter(
        path,
        name=name,
        cache_bytes=options.mdict_cache_bytes,
        max_block_bytes=options.mdict_max_block_bytes,
        max_article_bytes=options.mdict_max_article_bytes,
        max_resource_bytes=options.max_resource_bytes,
    )


def _build_dsl(path: Path, name: str | None, options: FactoryOptions) -> DictionaryAdapter:
    from .dsl import DSLAdapter

    return DSLAdapter(path, name=name, max_resource_bytes=options.max_resource_bytes)


def _build_stardict(path: Path, name: str | None, options: FactoryOptions) -> DictionaryAdapter:
    from .stardict import StarDictAdapter

    return StarDictAdapter(path, name=name, max_resource_bytes=options.max_resource_bytes)


register_reader(ReaderRegistration("mdict", (".mdx",), _build_mdict))
register_reader(ReaderRegistration("dsl", (".dsl", ".dsl.dz"), _build_dsl))
register_reader(ReaderRegistration("stardict", (".ifo",), _build_stardict))
