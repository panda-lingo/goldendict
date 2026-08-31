"""Thin adapters for the selected-source GoldenDict-ng worker."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import RLock, Thread
from typing import Any, Final, TextIO

from ..text import normalize_resource_key
from ..transform import (
    decode_css,
    etag_for,
    media_type_for,
    rewrite_css_urls,
)
from .base import (
    DictionaryAdapter,
    DictionaryArticle,
    DictionaryMetadata,
    DictionaryResource,
)


logger = logging.getLogger(__name__)
_EOF: Final = object()
_FORMAT_NAMES: Final = {"mdx": "mdict"}
SUPPORTED_LOCAL_FORMATS: Final = (
    "bgl",
    "stardict",
    "lsa",
    "dsl",
    "dictd",
    "xdxf",
    "sdict",
    "aard",
    "zipsounds",
    "mdx",
    "gls",
    "slob",
    "zim",
    "epwing",
)


class NativeWorkerError(RuntimeError):
    """The native process or its protocol failed."""


class NativeWorkerRequestError(NativeWorkerError):
    """GoldenDict-ng rejected one otherwise valid protocol request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NativeDictionaryDescriptor:
    dictionary_id: str
    name: str
    format: str
    word_count: int
    main_path: Path
    source_language: str | None = None
    target_language: str | None = None
    icon_resource_path: str | None = None


@dataclass(frozen=True, slots=True)
class NativeLookupArticle:
    dictionary_id: str
    html: str


@dataclass(frozen=True, slots=True)
class NativeLookupResult:
    articles: tuple[NativeLookupArticle, ...]
    suggestions: tuple[str, ...]


class NativeWorkerClient:
    """Own one serialized request channel to a headless GoldenDict-ng process."""

    def __init__(
        self,
        executable: Path,
        dictionary_roots: tuple[Path, ...],
        index_dir: Path,
        *,
        startup_timeout_seconds: float = 600,
        request_timeout_seconds: float = 45,
    ) -> None:
        if not dictionary_roots:
            raise NativeWorkerError("at least one dictionary root is required")
        index_dir.mkdir(parents=True, exist_ok=True)
        command = [str(executable)]
        for root in dictionary_roots:
            command.extend(("--dictionary-root", str(root)))
        command.extend(
            (
                "--index-dir",
                str(index_dir),
                "--timeout-ms",
                str(max(1, int(request_timeout_seconds * 1000))),
            )
        )
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            raise NativeWorkerError(f"could not start {executable}: {error}") from error

        self._messages: Queue[dict[str, Any] | object] = Queue()
        self._request_lock = RLock()
        self._closed = False
        self._next_id = 1
        # The worker owns the configured operation deadline. Leave a small
        # transport grace period for it to serialize and flush a timeout/error
        # response instead of racing the gateway's queue deadline.
        self._request_timeout_seconds = request_timeout_seconds + 1.0
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout_thread = Thread(
            target=self._read_stdout,
            args=(self._process.stdout,),
            name="goldendict-native-stdout",
            daemon=True,
        )
        self._stderr_thread = Thread(
            target=self._read_stderr,
            args=(self._process.stderr,),
            name="goldendict-native-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        try:
            ready = self._next_message(startup_timeout_seconds)
            if ready.get("event") != "ready":
                raise NativeWorkerError("native worker did not send a ready event")
            self.upstream_commit = _required_string(ready, "upstreamCommit")
            raw_formats = ready.get("supportedFormats")
            if (
                not isinstance(raw_formats, list)
                or any(not isinstance(value, str) for value in raw_formats)
                or tuple(raw_formats) != SUPPORTED_LOCAL_FORMATS
            ):
                raise NativeWorkerError(
                    "native worker does not provide the complete GoldenDict-ng local format set"
                )
            self.supported_formats = tuple(raw_formats)
            raw_dictionaries = ready.get("dictionaries")
            if not isinstance(raw_dictionaries, list):
                raise NativeWorkerError("native ready event has no dictionary list")
            dictionaries = tuple(_descriptor(value) for value in raw_dictionaries)
            if any(value.format not in SUPPORTED_LOCAL_FORMATS for value in dictionaries):
                raise NativeWorkerError("native worker published an unknown dictionary format")
            self.dictionaries = dictionaries
        except Exception:
            self.close()
            raise

    def request(self, operation: str, **values: Any) -> Any:
        with self._request_lock:
            if self._closed:
                raise NativeWorkerError("native worker is closed")
            request_id = self._next_id
            self._next_id += 1
            payload = {"id": request_id, "op": operation, **values}
            assert self._process.stdin is not None
            try:
                self._process.stdin.write(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise NativeWorkerError("native worker stopped accepting requests") from error
            response = self._next_message(self._request_timeout_seconds)
            if response.get("id") != request_id:
                raise NativeWorkerError("native worker response ID did not match the request")
            if response.get("ok") is not True:
                raw_error = response.get("error")
                if not isinstance(raw_error, dict):
                    raise NativeWorkerError("native worker returned a malformed error")
                raise NativeWorkerRequestError(
                    str(raw_error.get("code") or "nativeRequestFailed"),
                    str(raw_error.get("message") or "GoldenDict-ng request failed"),
                )
            return response.get("result")

    def lookup_batch(
        self,
        word: str,
        dictionary_ids: list[str],
        suggestion_limit: int,
    ) -> NativeLookupResult:
        """Run one native lookup across the selected GoldenDict-ng catalog."""

        result = self.request(
            "lookup",
            word=word,
            dictionaryIds=dictionary_ids,
            suggestionLimit=min(max(suggestion_limit, 0), 100),
        )
        if not isinstance(result, dict):
            raise NativeWorkerError("native lookup returned a malformed result")
        raw_articles = result.get("articles")
        raw_suggestions = result.get("suggestions")
        if not isinstance(raw_articles, list) or not isinstance(raw_suggestions, list):
            raise NativeWorkerError("native lookup returned malformed articles or suggestions")
        articles: list[NativeLookupArticle] = []
        for value in raw_articles:
            if not isinstance(value, dict):
                raise NativeWorkerError("native lookup article is not an object")
            articles.append(
                NativeLookupArticle(
                    dictionary_id=_required_string(value, "dictionaryId"),
                    html=_string(value, "html"),
                )
            )
        if any(not isinstance(value, str) for value in raw_suggestions):
            raise NativeWorkerError("native lookup suggestions contain a non-string value")
        return NativeLookupResult(
            articles=tuple(articles),
            suggestions=tuple(raw_suggestions),
        )

    def suggestions_batch(
        self,
        prefix: str,
        dictionary_ids: list[str],
        limit: int,
    ) -> tuple[str, ...]:
        result = self.request(
            "suggestions",
            prefix=prefix,
            dictionaryIds=dictionary_ids,
            limit=min(max(limit, 1), 100),
        )
        if not isinstance(result, dict) or not isinstance(result.get("suggestions"), list):
            raise NativeWorkerError("native suggestions returned a malformed result")
        values = result["suggestions"]
        if any(not isinstance(value, str) for value in values):
            raise NativeWorkerError("native suggestions contain a non-string value")
        return tuple(values)

    def close(self) -> None:
        with self._request_lock:
            if self._closed:
                return
            self._closed = True
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except OSError:
                    pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)

    def _next_message(self, timeout_seconds: float) -> dict[str, Any]:
        try:
            value = self._messages.get(timeout=max(0.001, timeout_seconds))
        except Empty as error:
            raise NativeWorkerError("timed out waiting for the native worker") from error
        if value is _EOF:
            code = self._process.poll()
            suffix = "" if code is None else f" (exit code {code})"
            raise NativeWorkerError("native worker closed its output" + suffix)
        assert isinstance(value, dict)
        return value

    def _read_stdout(self, stream: TextIO) -> None:
        try:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    self._messages.put(
                        {
                            "ok": False,
                            "error": {
                                "code": "invalidWorkerJson",
                                "message": "native worker emitted invalid JSON",
                            },
                        }
                    )
                    continue
                if isinstance(value, dict):
                    self._messages.put(value)
                else:
                    self._messages.put(
                        {
                            "ok": False,
                            "error": {
                                "code": "invalidWorkerJson",
                                "message": "native worker emitted a non-object JSON value",
                            },
                        }
                    )
        finally:
            self._messages.put(_EOF)

    @staticmethod
    def _read_stderr(stream: TextIO) -> None:
        for line in stream:
            logger.info("goldendict-native-worker: %s", line.rstrip())


class NativeDictionaryAdapter(DictionaryAdapter):
    """Expose one dictionary owned by a shared native process."""

    def __init__(
        self,
        client: NativeWorkerClient,
        descriptor: NativeDictionaryDescriptor,
        *,
        max_resource_bytes: int,
    ) -> None:
        self._client = client
        self._max_resource_bytes = max(0, max_resource_bytes)
        self.metadata = DictionaryMetadata(
            dictionary_id=descriptor.dictionary_id,
            name=descriptor.name,
            format=_FORMAT_NAMES.get(descriptor.format.casefold(), descriptor.format.casefold()),
            word_count=descriptor.word_count,
            main_path=descriptor.main_path,
            source_language=descriptor.source_language,
            target_language=descriptor.target_language,
            icon_resource_path=descriptor.icon_resource_path,
        )

    @property
    def client(self) -> NativeWorkerClient:
        return self._client

    def lookup(self, word: str) -> DictionaryArticle | None:
        result = self._client.lookup_batch(word, [self.metadata.dictionary_id], 0)
        for article in result.articles:
            if article.dictionary_id != self.metadata.dictionary_id:
                continue
            return DictionaryArticle(
                # GoldenDict-ng has already produced its canonical article
                # fragment. The frontend package understands its bres/gdau/
                # gdlookup schemes without a lossy HTML parse/reserialize pass.
                html=article.html,
                headword=word,
            )
        return None

    def suggestions(self, prefix: str, limit: int) -> list[str]:
        return list(
            self._client.suggestions_batch(
                prefix,
                [self.metadata.dictionary_id],
                limit,
            )[:limit]
        )

    def resource(self, resource_path: str) -> DictionaryResource | None:
        try:
            key = normalize_resource_key(
                resource_path,
                decode_percent=False,
                fold_case=False,
            )
        except ValueError:
            return None
        if _local_resource_escapes(self.metadata.main_path, key):
            return None
        try:
            result = self._client.request(
                "resource",
                dictionaryId=self.metadata.dictionary_id,
                path=key,
            )
        except NativeWorkerRequestError as error:
            if error.code == "resourceNotFound":
                return None
            raise
        if not isinstance(result, dict):
            raise NativeWorkerError("native resource returned a malformed result")
        encoded = result.get("bodyBase64")
        if not isinstance(encoded, str):
            raise NativeWorkerError("native resource result has no body")
        # Reject an oversized representation before creating the decoded copy.
        if len(encoded) > ((self._max_resource_bytes + 2) // 3) * 4 + 4:
            raise NativeWorkerError("dictionary resource exceeds the configured size limit")
        try:
            body = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise NativeWorkerError("native resource body is not valid base64") from error
        if len(body) > self._max_resource_bytes:
            raise NativeWorkerError("dictionary resource exceeds the configured size limit")
        worker_media_type = result.get("mediaType")
        media_type = (
            worker_media_type
            if isinstance(worker_media_type, str) and "/" in worker_media_type
            else media_type_for(key)
        )
        media_type = _known_image_media_type(body) or media_type
        if media_type.startswith("text/css"):
            body = rewrite_css_urls(
                decode_css(body),
                self.metadata.dictionary_id,
                resource_path=key,
                fold_case=False,
            ).encode("utf-8")
            if len(body) > self._max_resource_bytes:
                raise NativeWorkerError("rewritten dictionary resource exceeds the configured size limit")
            media_type = "text/css; charset=utf-8"
        return DictionaryResource(body=body, media_type=media_type, etag=etag_for(body))

    def close(self) -> None:
        # The service owns the shared process. Keeping adapter retirement a
        # no-op also lets an in-flight immutable catalog snapshot finish safely.
        return None


def _descriptor(value: object) -> NativeDictionaryDescriptor:
    if not isinstance(value, dict):
        raise NativeWorkerError("native dictionary metadata is not an object")
    word_count = value.get("wordCount")
    if isinstance(word_count, bool) or not isinstance(word_count, int) or word_count < 0:
        raise NativeWorkerError("native dictionary metadata has an invalid word count")
    return NativeDictionaryDescriptor(
        dictionary_id=_required_string(value, "id"),
        name=_required_string(value, "name"),
        format=_required_string(value, "format"),
        word_count=word_count,
        main_path=Path(_required_string(value, "mainPath")),
        source_language=_optional_string(value.get("sourceLanguage")),
        target_language=_optional_string(value.get("targetLanguage")),
        icon_resource_path=_optional_string(value.get("iconResourcePath")),
    )


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise NativeWorkerError(f"native message has no {key}")
    return result


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise NativeWorkerError(f"native message has no string {key}")
    return result


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _known_image_media_type(body: bytes) -> str | None:
    """Recognize formats that GoldenDict-ng may transcode behind the same key."""

    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def _local_resource_escapes(main_path: Path, resource_key: str) -> bool:
    """Reject filesystem sidecars whose resolved target leaves the bundle.

    This is gateway defense in depth for direct sidecars. The selected-source
    native patch separately enforces the same rule after MDD redirect
    resolution, where this adapter cannot see the final resource name.
    """

    try:
        resolved_main = main_path.resolve(strict=True)
        root = resolved_main if resolved_main.is_dir() else resolved_main.parent
        candidate = root.joinpath(*resource_key.split("/"))
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        # No direct sidecar exists, so GoldenDict-ng may still find this key in
        # an MDD or another format-owned resource store.
        return False
    except (OSError, RuntimeError):
        return True
    return not resolved.is_relative_to(root)
