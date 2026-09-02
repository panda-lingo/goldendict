"""Per-dictionary JSON metadata overrides.

The native worker remains the source of detected dictionary metadata.  An
adjacent ``<main filename>.json`` file can override the user-facing values for
one dictionary without coupling dictionaries that happen to share a folder.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Final


MAX_CONFIG_BYTES: Final = 64 * 1024
MAX_NAME_LENGTH: Final = 512
MAX_LANGUAGE_TAG_LENGTH: Final = 63
_ALLOWED_FIELDS: Final = frozenset({"name", "sourceLanguage", "targetLanguage"})
_LANGUAGE_TAG: Final = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


class DictionaryConfigError(ValueError):
    """A dictionary's optional JSON sidecar is present but invalid."""


@dataclass(frozen=True, slots=True)
class DictionaryConfig:
    name: str | None = None
    source_language: str | None = None
    target_language: str | None = None


def dictionary_config_path(main_path: Path) -> Path:
    """Return the unambiguous sidecar path for a dictionary main file."""

    return main_path.with_name(main_path.name + ".json")


def load_dictionary_config(main_path: Path) -> DictionaryConfig:
    """Load and validate one optional dictionary JSON sidecar.

    Missing files mean that all metadata continues to come from GoldenDict-ng.
    A present file is deliberately strict so a misspelled override cannot be
    silently ignored.
    """

    sidecar = dictionary_config_path(main_path)
    try:
        size = sidecar.stat().st_size
    except FileNotFoundError:
        return DictionaryConfig()
    except OSError as error:
        raise DictionaryConfigError(f"could not inspect {sidecar.name}: {error}") from error

    try:
        resolved_main = main_path.resolve(strict=True)
        resolved_sidecar = sidecar.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DictionaryConfigError(f"could not resolve {sidecar.name}: {error}") from error
    bundle_root = resolved_main if resolved_main.is_dir() else resolved_main.parent
    if not resolved_sidecar.is_relative_to(bundle_root):
        raise DictionaryConfigError(f"{sidecar.name} resolves outside the dictionary bundle")
    if not resolved_sidecar.is_file():
        raise DictionaryConfigError(f"{sidecar.name} is not a regular file")
    if size > MAX_CONFIG_BYTES:
        raise DictionaryConfigError(
            f"{sidecar.name} exceeds the {MAX_CONFIG_BYTES}-byte metadata limit"
        )

    try:
        raw = resolved_sidecar.read_bytes()
    except OSError as error:
        raise DictionaryConfigError(f"could not read {sidecar.name}: {error}") from error
    if len(raw) > MAX_CONFIG_BYTES:
        raise DictionaryConfigError(
            f"{sidecar.name} exceeds the {MAX_CONFIG_BYTES}-byte metadata limit"
        )
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DictionaryConfigError(f"{sidecar.name} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise DictionaryConfigError(f"{sidecar.name} must contain a JSON object")

    unknown = sorted(key for key in value if key not in _ALLOWED_FIELDS)
    if unknown:
        raise DictionaryConfigError(
            f"{sidecar.name} contains unknown field(s): {', '.join(unknown)}"
        )

    return DictionaryConfig(
        name=_optional_name(value.get("name"), sidecar.name),
        source_language=_optional_language(
            value.get("sourceLanguage"), "sourceLanguage", sidecar.name
        ),
        target_language=_optional_language(
            value.get("targetLanguage"), "targetLanguage", sidecar.name
        ),
    )


def normalize_language_tag(value: str) -> str:
    """Normalize a BCP-47-style language tag for output and comparison."""

    normalized = value.strip().replace("_", "-")
    if (
        not normalized
        or len(normalized) > MAX_LANGUAGE_TAG_LENGTH
        or not _LANGUAGE_TAG.fullmatch(normalized)
    ):
        raise ValueError("must be a language tag such as 'en' or 'zh-Hant'")
    return normalized.casefold()


def language_matches(value: str | None, requested: str) -> bool:
    """Apply RFC 4647-style basic filtering to one optional language tag."""

    if value is None:
        return False
    try:
        candidate = normalize_language_tag(value)
    except ValueError:
        return False
    return candidate == requested or candidate.startswith(requested + "-")


def _optional_name(value: object, filename: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DictionaryConfigError(f"{filename} field name must be a string or null")
    normalized = value.strip()
    if not normalized:
        raise DictionaryConfigError(f"{filename} field name must not be blank")
    if len(normalized) > MAX_NAME_LENGTH:
        raise DictionaryConfigError(
            f"{filename} field name exceeds {MAX_NAME_LENGTH} characters"
        )
    return normalized


def _optional_language(value: object, field: str, filename: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DictionaryConfigError(f"{filename} field {field} must be a string or null")
    if value.strip().casefold() == "auto":
        return None
    try:
        return normalize_language_tag(value)
    except ValueError as error:
        raise DictionaryConfigError(f"{filename} field {field} {error}") from error
