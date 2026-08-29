"""On-disk dictionary reader implementations."""

from .base import (
    DictionaryAdapter,
    DictionaryArticle,
    DictionaryMetadata,
    DictionaryResource,
    UnsupportedDictionaryFormat,
)

__all__ = [
    "DictionaryAdapter",
    "DictionaryArticle",
    "DictionaryMetadata",
    "DictionaryResource",
    "UnsupportedDictionaryFormat",
]
