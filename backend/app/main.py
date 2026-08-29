"""FastAPI application and format-neutral REST routes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings
from .errors import ServiceError
from .models import (
    DictionaryInfo,
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    LoadDictionaryRequest,
    LookupResponse,
    SuggestionsResponse,
)
from .service import DictionaryService


logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    service = DictionaryService(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if resolved_settings.startup_scan:
            await asyncio.to_thread(service.scan)
        else:
            service.ready = True
        try:
            yield
        finally:
            await asyncio.to_thread(service.close)

    app = FastAPI(
        title="GoldenDict Dictionary API",
        description=(
            "Dictionary-only REST service for loading configured local dictionary files, "
            "looking up headwords, and serving article resources."
        ),
        version=__version__,
        lifespan=lifespan,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.state.dictionary_service = service
    origins = list(resolved_settings.cors_origins or ("*",))
    mutation_methods = ["POST", "DELETE"] if resolved_settings.runtime_catalog_mutations else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "OPTIONS", *mutation_methods],
        allow_headers=["Accept", "Content-Type", "If-None-Match", "Range"],
        expose_headers=["Accept-Ranges", "Cache-Control", "Content-Range", "ETag"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                error=ErrorBody(code=error.code, message=error.message, details=error.details)
            ).model_dump(by_alias=True),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=ErrorBody(
                    code="validationFailed",
                    message="The request did not match the API contract.",
                    details={"violations": details},
                )
            ).model_dump(by_alias=True),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, error: HTTPException) -> JSONResponse:
        message = error.detail if isinstance(error.detail, str) else "The request could not be completed."
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content=ErrorResponse(
                error=ErrorBody(code="httpError", message=message)
            ).model_dump(by_alias=True),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled dictionary API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorBody(
                    code="internalError",
                    message="The dictionary service encountered an unexpected error.",
                )
            ).model_dump(by_alias=True),
        )

    @app.get(f"{API_PREFIX}/health", response_model=HealthResponse, tags=["service"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok" if service.ready else "starting",
            ready=service.ready,
            dictionary_count=len(service.catalog.snapshot().adapters),
            version=__version__,
            startup_errors=service.startup_errors,
        )

    @app.get(f"{API_PREFIX}/dictionaries", response_model=list[DictionaryInfo], tags=["dictionaries"])
    async def dictionaries() -> list[DictionaryInfo]:
        return service.dictionaries()

    if resolved_settings.runtime_catalog_mutations:

        @app.post(
            f"{API_PREFIX}/dictionaries/load",
            response_model=DictionaryInfo,
            status_code=status.HTTP_201_CREATED,
            tags=["dictionaries"],
        )
        async def load_dictionary(body: LoadDictionaryRequest) -> DictionaryInfo:
            return await asyncio.to_thread(service.load, body.path, body.name)

        @app.delete(
            f"{API_PREFIX}/dictionaries/{{dictionary_id}}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["dictionaries"],
        )
        async def unload_dictionary(
            dictionary_id: Annotated[str, Path(min_length=1, max_length=128)],
        ) -> Response:
            await asyncio.to_thread(service.unload, dictionary_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(f"{API_PREFIX}/lookup/{{word:path}}", response_model=LookupResponse, tags=["lookup"])
    async def lookup(
        word: Annotated[str, Path(min_length=1)],
        dictionary_ids: Annotated[list[str] | None, Query()] = None,
    ) -> LookupResponse:
        return await asyncio.to_thread(service.lookup, word, _dictionary_ids(dictionary_ids))

    @app.get(f"{API_PREFIX}/suggestions", response_model=SuggestionsResponse, tags=["lookup"])
    async def suggestions(
        prefix: Annotated[str, Query(min_length=1)],
        dictionary_ids: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> SuggestionsResponse:
        return await asyncio.to_thread(
            service.suggestions,
            prefix,
            _dictionary_ids(dictionary_ids),
            limit,
        )

    @app.get(
        f"{API_PREFIX}/dictionaries/{{dictionary_id}}/resources/{{resource_path:path}}",
        responses={200: {"content": {"application/octet-stream": {}}}, 304: {"description": "Not modified"}},
        tags=["resources"],
    )
    async def dictionary_resource(
        request: Request,
        dictionary_id: Annotated[str, Path(min_length=1, max_length=128)],
        resource_path: Annotated[str, Path(min_length=1, max_length=4096)],
    ) -> Response:
        adapter = service.adapter(dictionary_id)
        resource = await asyncio.to_thread(adapter.resource, resource_path)
        if resource is None:
            raise HTTPException(status_code=404, detail="Dictionary resource not found.")
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": resource.cache_control,
            "ETag": resource.etag,
            "X-Content-Type-Options": "nosniff",
        }
        if request.headers.get("if-none-match") == resource.etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
        requested_range = request.headers.get("range")
        if requested_range:
            selected = _byte_range(requested_range, len(resource.body))
            if selected is None:
                return Response(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    headers={**headers, "Content-Range": f"bytes */{len(resource.body)}"},
                )
            start, end = selected
            return Response(
                content=resource.body[start : end + 1],
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=resource.media_type,
                headers={**headers, "Content-Range": f"bytes {start}-{end}/{len(resource.body)}"},
            )
        return Response(
            content=resource.body,
            media_type=resource.media_type,
            headers=headers,
        )

    return app


def _dictionary_ids(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    parsed = [part.strip() for value in values for part in value.split(",") if part.strip()]
    return parsed or None


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    if size <= 0 or not value.casefold().startswith("bytes=") or "," in value:
        return None
    specification = value[6:].strip()
    start_text, separator, end_text = specification.partition("-")
    if not separator:
        return None
    try:
        if not start_text:
            suffix_size = int(end_text)
            if suffix_size <= 0:
                return None
            start = max(0, size - suffix_size)
            return start, size - 1
        start = int(start_text)
        if start < 0 or start >= size:
            return None
        end = int(end_text) if end_text else size - 1
        if end < start:
            return None
        return start, min(end, size - 1)
    except ValueError:
        return None


app = create_app()
