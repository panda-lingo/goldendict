# GoldenDict Dictionary API

This directory contains a dictionary-only FastAPI service. It scans explicitly
configured server-local roots, performs lookups, and serves the resources needed
to render returned HTML. It does not expose file upload or delete dictionary
files. The catalog is read-only after startup by default.

## Supported readers

- MDict `.mdx`, companion `.mdd`/`.1.mdd` volumes, and same-basename sidecar
  CSS, JavaScript, icons, fonts, audio, and video.
- ABBYY Lingvo DSL `.dsl`/`.dsl.dz`, aliases, common DSL markup, and companion
  `.files` resource directories.
- StarDict `.ifo` bundles with `.idx`/`.idx.gz`, `.dict`/`.dict.dz`, `.syn`,
  typed fields, and `res`/`.res` resource directories.

The default container builds a pinned, selected-source GoldenDict-ng C++ worker
and uses its `Mdx`, `Dsl`, and `Stardict` factories directly. The thin FastAPI
process keeps the REST contract stable and owns one JSON-lines worker for the
startup catalog. The Python readers remain an explicit fallback image and are
also used for files that a non-required native worker declines.

In the Python fallback only, MDict records and MDD bodies are decompressed
lazily. That reader retains the readmdict key table and a normalized headword
index, but not every article or resource body. Its decompressed record blocks
use a bounded LRU configured by `GOLDENDICT_MDICT_CACHE_BYTES`; these settings do
not tune GoldenDict-ng's native index implementation.

## Run

From the repository root, build the preferred combined native runtime against a
local GoldenDict-ng checkout and mount dictionaries read-only:

```bash
make build-backend-native GOLDENDICT_NG_SOURCE=/absolute/goldendict-ng
GOLDENDICT_DICTIONARY_PATH=/absolute/dictionaries docker compose up --no-build
```

`make build-backend-native` verifies the pinned upstream commit and records a
deterministic digest for intentional local `src/` modifications, including when
the source is a linked Git worktree. Native indices persist in the Compose
`native-indices` volume. No upload or runtime catalog-mutation route is enabled.

The Python-only development/fallback service can still run directly:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
GOLDENDICT_DICTIONARY_ROOTS=/absolute/dictionaries uvicorn app.main:app --port 8080
```

Or build that explicit fallback image from the repository root:

```bash
docker build -f backend/Dockerfile -t goldendict-api:python backend
docker run --rm -p 8080:8080 \
  -v /absolute/dictionaries:/dictionaries:ro \
  goldendict-api:python
```

The image runs as UID/GID `10001` and expects dictionary roots to be mounted
read-only. One worker is intentional: every additional worker owns another
MDict key index. Scale with multiple containers only after measuring memory.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOLDENDICT_DICTIONARY_ROOTS` | `./dictionaries` | `:`-separated allowed scan/load roots on Unix |
| `GOLDENDICT_STARTUP_SCAN` | `true` | Recursively scan allowed roots at startup |
| `GOLDENDICT_RUNTIME_CATALOG_MUTATIONS` | `false` | Opt in to server-path load and process-only unload routes |
| `GOLDENDICT_NATIVE_WORKER` | unset | Path to the GoldenDict-ng JSON-lines worker |
| `GOLDENDICT_NATIVE_INDEX_DIR` | `./.goldendict-native-indices` | Writable native index directory |
| `GOLDENDICT_NATIVE_REQUIRED` | `false` | Keep health unready if the configured worker fails or declines a native-format file |
| `GOLDENDICT_MDICT_CACHE_BYTES` | `33554432` | Per-volume decompressed block-cache budget |
| `GOLDENDICT_MDICT_MAX_BLOCK_BYTES` | `134217728` | Maximum compressed or declared decompressed MDict block |
| `GOLDENDICT_MDICT_MAX_ARTICLE_BYTES` | `33554432` | Maximum combined decoded article source per lookup |
| `GOLDENDICT_MAX_RESOURCE_BYTES` | `134217728` | Maximum resource response body |
| `GOLDENDICT_MAX_QUERY_LENGTH` | `512` | Maximum Unicode characters in a query |
| `GOLDENDICT_SUGGESTION_LIMIT` | `20` | Suggestions included with lookup responses |
| `GOLDENDICT_CORS_ORIGINS` | `*` | Comma-separated origins; add literal `null` for opted-in scripts in an opaque-origin iframe; wildcard disables credentials |

## REST contract

The OpenAPI document is available at `/openapi.json` and Swagger UI at `/docs`.
All JSON fields are camelCase. Errors have the stable shape
`{"error":{"code":"...","message":"...","details":{...}}}`.

```text
GET    /api/v1/health
GET    /api/v1/dictionaries
GET    /api/v1/lookup/{word}?dictionary_ids=id1,id2
GET    /api/v1/suggestions?prefix=hel&dictionary_ids=id1&limit=20
GET    /api/v1/dictionaries/{id}/resources/{path}
```

When `GOLDENDICT_RUNTIME_CATALOG_MUTATIONS=true`, two additional routes are
registered:

```text
POST   /api/v1/dictionaries/load
DELETE /api/v1/dictionaries/{id}
```

The POST route accepts a server-local path:

```json
{"path":"reference/oaldpe.mdx","name":"Oxford Advanced Learner's"}
```

Relative paths are resolved under the configured roots. Absolute paths and
symlinks are accepted only when their real target remains within one of those
roots. The service never fetches remote dictionary paths.

A successful lookup returns:

```json
{
  "word": "hello",
  "articles": [{
    "dictionaryId": "...",
    "dictionaryName": "...",
    "format": "mdict",
    "html": "<div class=\"mdict\">...</div>",
    "resourceBaseUrl": "/api/v1/dictionaries/.../resources/"
  }],
  "suggestions": ["hello"],
  "lookupTimeMs": 2
}
```

Native articles retain GoldenDict-ng's canonical `bres:`, `gdlookup:`, `gdau:`,
and `gdvideo:` URLs; the frontend package resolves them without a lossy server
parse/reserialize pass. Native CSS is rewritten at the resource boundary. The
Python fallback readers instead emit equivalent HTTP URLs and `data-gd-*`
markers directly.

## Security boundary

Dictionary files are untrusted active content. Native article scripts and inline
handlers are preserved across the backend boundary, but the frontend package
strips them by default. Its explicit `scriptPolicy="sandboxed"` compatibility
mode retains local sidecar scripts inside an opaque-origin iframe that never has
same-origin access to the host. Such frames send `Origin: null` for XHR/fetch,
which the Compose demo allows explicitly. Never inject `articles[].html` into an
application's privileged document. Resource paths are URL-decoded once,
normalized across slash conventions, and reject control characters, URI schemes,
and dot traversal. Resource responses include an ETag, cache policy, accurate
MIME type, and `X-Content-Type-Options: nosniff`.

## Verification

```bash
make test-native-worker GOLDENDICT_NG_SOURCE=/absolute/goldendict-ng
docker build --target test -f backend/Dockerfile -t goldendict-api-test backend
docker run --rm goldendict-api-test
```

This is the canonical backend test command and does not depend on host Python.
`requirements.txt` and `requirements-dev.txt` pin the direct dependency versions
verified by this image; `pyproject.toml` retains compatible library ranges for
downstream packaging.
The real integration check mounts the repository-adjacent fixture:

```bash
docker run --rm \
  -v /home/ubuntu/speak/examples/dict:/fixtures:ro \
  -e GOLDENDICT_TEST_MDX=/fixtures/oaldpe.mdx \
  goldendict-api-test python -m pytest -m integration
```

See `upstream-compatibility.yaml` before updating GoldenDict-ng or readmdict.

## Current limitations

- Encrypted/password-protected MDict files are not supported by the HTTP API.
- MDict's key table is still memory-resident because readmdict exposes it that
  way; record and resource bodies are lazy, and declared block sizes, article
  output, resource output, and decompressed caches have independent bounds.
- The Python fallback does not implement DSL/StarDict ZIP resource bundles or
  every GoldenDict-specific field/tag extension; the default native worker uses
  the pinned upstream implementations instead.
- Full GoldenDict-ng format parity requires additional adapters and fixtures.
- Dictionary JavaScript compatibility depends on the consuming iframe sandbox.
