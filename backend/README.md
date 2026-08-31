# GoldenDict Dictionary API

This directory contains a thin FastAPI gateway in front of the bundled
GoldenDict-ng C++ worker. GoldenDict-ng is the only dictionary loader and
parser. The gateway validates configured roots, publishes the worker's catalog,
batches lookups, and exposes article resources over a stable read-only REST
contract.

There is no Python format reader, upload endpoint, runtime load endpoint, or
unload endpoint. If the native process cannot start or rejects its protocol
contract, health remains unready and the catalog is empty.

## Supported local formats

The worker invokes the complete file-backed factory sequence from the pinned
GoldenDict-ng `LoadDictionaries::handlePath()` implementation:

1. BGL (`.bgl`)
2. StarDict (`.ifo` bundles)
3. LSA (`.lsa`)
4. ABBYY Lingvo DSL (`.dsl`, `.dsl.dz`)
5. DictD (`.index` bundles)
6. XDXF (`.xdxf`, `.xdxf.dz`)
7. SDict (`.dct`)
8. Aard (`.aar`)
9. ZipSounds (`.zips`)
10. MDict (`.mdx` plus MDD volumes and sidecars)
11. GLS (`.gls`, `.gls.dz`)
12. SLOB (`.slob`)
13. ZIM (`.zim` and split ZIM files)
14. EPWING (`catalogs` book trees)

Sound directories, Hunspell morphology, websites/network dictionaries,
programs, and transliterations are GoldenDict-ng configuration providers, not
file-backed dictionary formats, and are outside this mounted-file service.

Article HTML, prefix matching, dictionary icons, format resources, companion
files, and index behavior come from the pinned upstream C++ sources. Canonical
`bres:`, `gico:`, `gdlookup:`, `gdau:`, and `gdvideo:` URLs cross the gateway
unchanged and are resolved by the frontend package.

## Run

From the repository root, build the combined runtime against the locked
GoldenDict-ng checkout, then mount dictionaries read-only:

```bash
make build-backend-native GOLDENDICT_NG_SOURCE=/absolute/goldendict-ng
GOLDENDICT_DICTIONARY_PATH=/absolute/dictionaries docker compose up --no-build
```

The image runs as UID/GID `10001`. GoldenDict indices persist in the Compose
`native-indices` volume. Changing the mounted catalog requires a service
restart.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOLDENDICT_DICTIONARY_ROOTS` | `./dictionaries` | `:`-separated read-only dictionary roots on Unix |
| `GOLDENDICT_STARTUP_SCAN` | `true` | Start and publish the native catalog during application startup |
| `GOLDENDICT_NATIVE_WORKER` | `/usr/local/bin/goldendict-native-worker` | Required worker executable |
| `GOLDENDICT_NATIVE_INDEX_DIR` | `./.goldendict-native-indices` | Writable GoldenDict index directory |
| `GOLDENDICT_NATIVE_STARTUP_TIMEOUT_SECONDS` | `600` | Native indexing/startup timeout |
| `GOLDENDICT_NATIVE_REQUEST_TIMEOUT_SECONDS` | `45` | Lookup/resource protocol timeout |
| `GOLDENDICT_MAX_RESOURCE_BYTES` | `134217728` | Maximum decoded resource response |
| `GOLDENDICT_MAX_QUERY_LENGTH` | `512` | Maximum Unicode characters in a query |
| `GOLDENDICT_SUGGESTION_LIMIT` | `20` | Suggestions returned with a lookup |
| `GOLDENDICT_CORS_ORIGINS` | `*` | Comma-separated origins; add literal `null` for opaque-frame scripts |

## REST contract

The OpenAPI document is at `/openapi.json` and Swagger UI at `/docs`. JSON
fields are camelCase. Errors use
`{"error":{"code":"...","message":"...","details":{...}}}`.

```text
GET /api/v1/health
GET /api/v1/dictionaries
GET /api/v1/lookup/{word}?dictionary_ids=id1,id2
GET /api/v1/suggestions?prefix=hel&dictionary_ids=id1&limit=20
GET /api/v1/dictionaries/{id}/resources/{path}
```

A lookup across multiple dictionaries is sent to the worker once. The worker
overlaps GoldenDict-ng's shared synonym resolution with prefix work, then starts
every selected article request before waiting. Parsing, decompression, and I/O
therefore overlap as they do in the desktop application. DSL and MDX deferred
initialization is also started immediately after catalog construction.

## Security boundary

Dictionary files and their HTML are untrusted active content. Roots are
canonicalized before worker startup. Resource names are normalized and reject
control characters, URI schemes, and dot traversal. The selected-source MDX
adaptation additionally canonicalizes local/MDD redirect targets and blocks
symlinks outside the dictionary bundle.

Resource responses include an ETag, cache policy, accurate MIME type,
`X-Content-Type-Options: nosniff`, and
`Cross-Origin-Resource-Policy: cross-origin`. Never inject `articles[].html`
into a privileged document. The frontend isolates it in an opaque-origin
iframe. Its default sandboxed policy retains GoldenDict-ng script behavior
without same-origin access to the host; consumers can select the strict
`scriptPolicy = "none"` mode to strip scripts and inline handlers.

## Verification

```bash
make test-backend
make test-native-worker GOLDENDICT_NG_SOURCE=/absolute/goldendict-ng
```

The gateway suite uses protocol doubles and verifies the native-only startup
policy, one-operation batched lookup, worker lifecycle, resource containment,
MIME handling, caching, and immutable OpenAPI surface. The native gate compiles
all fourteen upstream factories, asserts the complete runtime format manifest,
creates DSL and StarDict fixtures, checks lookup/suggestions/icons/resources,
and starts the combined REST image.

See [upstream-compatibility.yaml](upstream-compatibility.yaml) and the
[native worker guide](native/README.md) before changing the GoldenDict-ng pin.
