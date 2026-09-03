from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dictionary_config import (
    DictionaryConfig,
    DictionaryConfigError,
    dictionary_config_path,
    language_matches,
    load_dictionary_config,
    normalize_language_tag,
)


def test_dictionary_config_overrides_name_and_normalizes_languages(tmp_path: Path) -> None:
    main_path = tmp_path / "fixture.mdx"
    main_path.touch()
    dictionary_config_path(main_path).write_text(
        json.dumps(
            {
                "name": "  Personal Oxford  ",
                "sourceLanguage": "EN_us",
                "targetLanguage": "zh-Hant",
            }
        ),
        encoding="utf-8",
    )

    config = load_dictionary_config(main_path)

    assert config == DictionaryConfig(
        name="Personal Oxford",
        source_language="en-us",
        target_language="zh-hant",
    )


def test_missing_and_auto_fields_keep_native_detection(tmp_path: Path) -> None:
    main_path = tmp_path / "fixture.dsl"
    main_path.touch()

    assert load_dictionary_config(main_path) == DictionaryConfig()

    dictionary_config_path(main_path).write_text(
        '{"sourceLanguage":"auto","targetLanguage":null}',
        encoding="utf-8",
    )
    assert load_dictionary_config(main_path) == DictionaryConfig()


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"displayName":"typo"}',
        '{"name":"  "}',
        '{"sourceLanguage":"not a language!"}',
        '{"targetLanguage":42}',
        "{not-json}",
    ],
)
def test_invalid_dictionary_config_is_rejected(tmp_path: Path, payload: str) -> None:
    main_path = tmp_path / "fixture.ifo"
    main_path.touch()
    dictionary_config_path(main_path).write_text(payload, encoding="utf-8")

    with pytest.raises(DictionaryConfigError):
        load_dictionary_config(main_path)


def test_dictionary_config_symlink_cannot_escape_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    main_path = bundle / "fixture.mdx"
    main_path.touch()
    outside = tmp_path / "outside.json"
    outside.write_text('{"name":"secret"}', encoding="utf-8")
    dictionary_config_path(main_path).symlink_to(outside)

    with pytest.raises(DictionaryConfigError, match="outside the dictionary bundle"):
        load_dictionary_config(main_path)


def test_language_tags_use_case_insensitive_basic_filtering() -> None:
    assert normalize_language_tag(" EN_us ") == "en-us"
    assert language_matches("en-US", "en") is True
    assert language_matches("en", "en-us") is False
    assert language_matches("French", "fr") is False
    assert language_matches(None, "en") is False
