"""Camel-case HTTP request and response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class DictionaryInfo(APIModel):
    id: str
    name: str
    format: str
    word_count: int
    source_language: str | None = None
    target_language: str | None = None
    icon_url: str | None = None
    resource_base_url: str


class ArticleResponse(APIModel):
    dictionary_id: str
    dictionary_name: str
    format: str
    html: str
    source_language: str | None = None
    target_language: str | None = None
    icon_url: str | None = None
    resource_base_url: str | None = None


class LookupResponse(APIModel):
    word: str
    articles: list[ArticleResponse]
    suggestions: list[str]
    lookup_time_ms: int


class SuggestionsResponse(APIModel):
    prefix: str
    suggestions: list[str]
    lookup_time_ms: int


class HealthResponse(APIModel):
    status: str
    ready: bool
    dictionary_count: int
    version: str
    startup_errors: list[str] = Field(default_factory=list)


class ErrorBody(APIModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(APIModel):
    error: ErrorBody
