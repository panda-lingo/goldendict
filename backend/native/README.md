# GoldenDict-ng native worker

This directory builds a small, headless JSON-lines worker around GoldenDict-ng's
real local-dictionary implementations. The HTTP service remains the stable
public boundary; the worker is an internal subprocess that reads dictionaries
from local paths at startup. It does not implement uploads, HTTP, or a second
public API.

The default deployment packages this worker and FastAPI together as
`goldendict-api:native`. FastAPI owns the versioned REST contract and translates
browser-facing links/resources; the subprocess owns GoldenDict-ng dictionary
loading and indices. The image also retains the Python readers so a custom
deployment can use them for unsupported or failed native loads without changing
the REST surface.

The current pin is recorded in [`upstream.lock`](upstream.lock). At configure
time, [`cmake/verify_upstream.cmake`](cmake/verify_upstream.cmake) verifies that:

- the requested build commit equals the lock;
- the supplied checkout is at exactly that commit; and
- the caller's dirty flag and diff digest match the effective source tree below
  `src/`.

The Docker build copies the Git checkout into its named build context, so the
same guard runs even when `build.sh` is bypassed. The worker also publishes the
verified commit, dirty state, and diff digest in its startup event. Local fixes
and intentional patches on the pinned commit are supported without losing
provenance: [`provenance.sh`](provenance.sh) creates a disposable Git index and
SHA-256-hashes a canonical binary diff containing tracked changes/deletions and
all untracked `src/` content, including ignored generated headers. It never
changes the developer's real index.

## Architecture and scope

The executable compiles a deliberately explicit set of GoldenDict-ng sources
from the pinned checkout. MDX/MDD, DSL, and StarDict parsing, index construction,
headword matching, article rendering, resource retrieval, and GoldenDict link
rewriting therefore come from upstream C++; this project does not maintain
parallel parsers for those formats.

The integration boundary is GoldenDict-ng's `Dictionary::Class` interface and
the `Mdx::makeDictionaries`, `Dsl::makeDictionaries`, and
`Stardict::makeDictionaries` factories. Small headers under `shims/` replace
only desktop services that these implementations include but REST headword
lookup does not use: application configuration, the global UI broadcaster,
full-text search, audio-link UI registration, and two small headless helpers for
TIFF-to-PNG conversion and XDXF language lookup. Interface drift is intentional
compile-time breakage.

There is one explicit security adaptation to an upstream translation unit:
[`cmake/prepare_mdx_source.cmake`](cmake/prepare_mdx_source.cmake) creates the
compiled copy of `mdx.cc` and replaces only `loadResourceFile` with a canonical
dictionary-directory guard. It runs for the original request and every MDD
`@@@LINK` redirect, preserving nested and case-sensitive local sidecars while
blocking dot traversal and symlinks that resolve outside the bundle. Both exact
source anchors must match once or configuration fails, so an upstream edit
forces a deliberate rebase. The build executes the focused
`resource-guard-test`; no MDX parser implementation is copied into this project.

Current native scope is **MDX with companion MDD resources, DSL (including
dictzip-compressed DSL), and StarDict**. The worker recursively enumerates local
files under every supplied root and lets each upstream factory recognize its
own primary and companion files.

One fail-closed source transformation is applied to upstream `mdx.cc` by
`cmake/prepare_mdx_source.cmake`. GoldenDict-ng's trusted desktop environment
allows the MDD `@@@LINK` target to reach a sibling local file directly; an HTTP
service must instead canonicalize that final target after every redirect and
reject dot traversal or symlinks outside the dictionary directory. The shared
`resource_guard.hh` keeps nested, case-sensitive sidecars such as
`scripts/Dictionary-UI.js` working. Its C++ test runs during every Docker build,
and the exact transformation intentionally fails configure when the upstream
function changes so an upgrade cannot silently lose the boundary.

FastAPI performs the same configured-root startup scan, starts the worker with
those roots, and joins worker dictionaries to scanned files by canonical
`mainPath`. `GOLDENDICT_NATIVE_REQUIRED` controls failure policy:

- `true` (the combined image and Compose default) keeps health unready if the
  worker fails or does not publish a discovered MDX, DSL, or StarDict main file;
- `false` prefers native dictionaries but lets Python adapters cover scan items
  the worker did not publish; and
- omitting `GOLDENDICT_NATIVE_WORKER` loads the startup scan entirely through
  Python adapters.

In every mode dictionary roots are server-local paths, normally read-only
mounts. There is no upload or delete API. The optional runtime catalog routes
accept server paths only and mutate in-memory catalog state, not source files.

GoldenDict-ng also has format factories for BGL, LSA, DictD, XDXF, SDict, Aard,
ZipSounds, GLS, SLOB, ZIM, and EPWING. Those are possible future native adapters,
not formats supported by this binary today. Each brings its own source and
dependency set and should be added explicitly.

### Why not call `loadDictionaries`?

GoldenDict-ng's top-level `loadDictionaries` is a desktop application
orchestrator, not a headless library entry point. Its interface and execution
path require a `QWidget`, the full application `Config::Class`, a
`QNetworkAccessManager`, initialization/splash UI, message boxes and event-loop
behavior, global application services, network dictionaries, and
transliterations. Linking it would pull the REST backend toward the whole
desktop application and make upgrades more fragile.

Calling the individual format factory preserves upstream parsing behavior while
keeping a narrow, testable boundary. If upstream later exposes a supported
headless loader library, replacing this selected-source bridge with that API is
the preferred migration.

## Build

The default build produces the combined REST/native image from a local
GoldenDict-ng checkout at the locked commit:

```sh
make build-backend-native \
  GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng
```

This produces `goldendict-api:native`. The Make target delegates to
`backend/native/build.sh`, which resolves ordinary checkouts and linked Git
worktrees through `git -C`, computes commit/dirty/diff attestation against the
live source, and supplies it to `backend/Dockerfile.native`. Compose instead
passes the checkout as its named `goldendict-ng` build context:

```sh
GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng \
GOLDENDICT_DICTIONARY_PATH=/absolute/path/to/dictionaries \
  docker compose up --build
```

To build only the standalone protocol worker image:

```sh
backend/native/build.sh /home/ubuntu/goldendict-ng
```

It produces `goldendict-native-worker:dev`. An explicit equivalent is:

```sh
docker build \
  --build-context goldendict-ng=/home/ubuntu/goldendict-ng \
  --build-arg GOLDENDICT_NG_COMMIT=5ad66765aa423d381025566bff990f7d8007be84 \
  --tag goldendict-native-worker:dev \
  backend/native
```

A commit mismatch, caller-supplied provenance mismatch, unversioned source
directory, or incompatible upstream interface fails with a direct diagnostic.
When a linked worktree's `.git` pointer cannot resolve inside Docker, CMake uses
the commit/digest pair that the wrapper computed immediately before copying the
context. A direct Docker build without usable Git metadata must supply that
attestation explicitly.

For release/CI builds, require an entirely clean relevant source tree:

```sh
GOLDENDICT_NG_REQUIRE_CLEAN=ON \
  backend/native/build.sh /home/ubuntu/goldendict-ng
```

The direct Docker equivalent is
`--build-arg GOLDENDICT_NG_REQUIRE_CLEAN=ON`. Without that flag, intentional
local source changes build successfully and are attested in the worker's ready
event. Do not disable commit checking to make an upgrade compile.

The build dependencies are CMake, C and C++17 compilers, Git, Qt 6 Core/
Concurrent/Gui/Svg/Widgets/Xml development files, fmt, zlib, bzip2, liblzma,
liblzo2, and the platform iconv implementation. The runtime image retains the
corresponding Qt and compression libraries. Qt Gui, Svg, and Widgets are
currently required by upstream dictionary/common source signatures even though
the process creates no UI. WebEngine, Multimedia, Xapian, ZIM, and EPWING are
not linked.

The selected-source approach currently compiles 26 upstream C++ files and one C
file, plus the `Dictionary::Class` QObject header. Its meaningful runtime costs
are the Qt Gui/Widgets/Svg dependency, one GoldenDict index per dictionary in
the writable index directory, the opened dictionary data, and base64 expansion
for resource payloads across the JSON-lines boundary. Initial startup can be
slow because new or stale indices are built before the `ready` event; later
starts reuse them. For scale, the tested Ubuntu 24.04 arm64 image is about 393
MB uncompressed (`docker image inspect .Size`), while the stripped worker is
about 1.15 MB. The measured combined `goldendict-api:native` arm64 image is
486,239,872 bytes uncompressed. Most image weight is the Python, Qt, and graphics
runtime rather than the worker executable. Re-measure for the deployment
architecture and after every format or dependency change.

## Run

The default Compose `api` service runs the combined image as UID 10001, mounts
`${GOLDENDICT_DICTIONARY_PATH}` read-only at `/dictionaries`, scans it on
startup, and persists GoldenDict indices in the `native-indices` volume. No
dictionary bytes are uploaded through the service. The opt-in Python-only
comparison/fallback service runs on port 8081:

```sh
docker compose --profile python-fallback up --build api-python
```

To run the standalone worker protocol directly, mount dictionary data read-only
and ensure any persistent index mount is writable by UID 10001:

```sh
docker run --rm -i \
  --mount type=bind,src=/absolute/path/to/dictionaries,dst=/dictionaries,readonly \
  goldendict-native-worker:dev
```

Without an index mount, indices live in the container's writable layer. For a
persistent index, mount a UID-10001-writable directory at
`/var/lib/goldendict/indices`.

Executable options are:

```text
goldendict-native-worker \
  --dictionary-root PATH [--dictionary-root PATH ...] \
  [--index-dir PATH] [--timeout-ms N]
```

Index/load progress is written to stderr. Stdout is reserved for protocol
messages and must not be merged with stderr.

## JSON-lines protocol

Each stdout or stdin line is one compact JSON object. After all dictionaries
are indexed and loaded, the first stdout line is:

```json
{"event":"ready","upstreamCommit":"5ad66765aa423d381025566bff990f7d8007be84","upstreamDirty":false,"upstreamDiffSha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","dictionaries":[{"id":"...","name":"...","format":"mdx","wordCount":123,"sourceLanguage":"en","targetLanguage":null,"iconUrl":null,"resourceBaseUrl":"/api/v1/dictionaries/.../resources/","mainPath":"/dictionaries/example.mdx"}]}
```

The displayed digest is SHA-256 of an empty diff, which is the expected value
when `upstreamDirty` is false.

Requests contain a caller-chosen `id` and an `op`. Responses preserve the `id`
and use either `{"ok":true,"result":...}` or
`{"ok":false,"error":{"code":"...","message":"..."}}`.

```json
{"id":"1","op":"list"}
{"id":"2","op":"lookup","word":"hello","dictionaryIds":["dictionary-id"]}
{"id":"3","op":"suggestions","prefix":"hel","limit":20,"dictionaryIds":["dictionary-id"]}
{"id":"4","op":"resource","dictionaryId":"dictionary-id","path":"style.css"}
```

`dictionaryIds` is optional for lookup and suggestions; omission selects every
loaded dictionary. A lookup result contains `word`, `articles`, `suggestions`,
and `lookupTimeMs`. A resource result contains `dictionaryId`, `path`, detected
`mediaType`, and `bodyBase64`. Article HTML intentionally retains GoldenDict-ng
schemes such as `bres:`, `gdlookup:`, and `gdau:` for translation by the HTTP/
frontend layer.

That preservation includes OALDPE references to `bres://.../oaldpe.js` and
`bres://.../oaldpe-jquery.js`. Native resource lookup and the REST route serve
those local sidecars as `text/javascript`; REST also sets
`X-Content-Type-Options: nosniff`. Serving them does not opt into execution. The
frontend's safe `scriptPolicy` default strips scripts and inline handlers; a
consumer must explicitly choose `scriptPolicy = "sandboxed"`, which still runs
the article in an opaque-origin iframe without host same-origin access. Requests
from that iframe carry Origin `null`. Compose permits
`http://localhost:5173,null` so its demo can fetch resources after that explicit
opt-in; allow the `null` CORS origin only where the opaque-origin sandbox is an
intended trust boundary. The backend's default wildcard policy is unchanged.

The protocol is synchronous today: send the next request after consuming the
previous response. EOF on stdin shuts down the worker. Kill the process to abort
startup indexing.

## Generated protocol smoke test

After (or as part of) building the combined image, run:

```sh
make test-native-worker
```

The target builds/uses `goldendict-api:native` and runs
`backend/native/tests/protocol_smoke.py`. The test generates minimal DSL and
StarDict bundles instead of depending on copyrighted fixtures, then checks the
ready event, dictionary metadata and `mainPath`, exact lookup format/content,
and prefix suggestions. It also reports the ready event's upstream commit/dirty
provenance.

## Upgrading GoldenDict-ng

Treat an upstream bump as a compatibility change, even if it compiles:

1. Check out the candidate GoldenDict-ng commit in a clean worktree.
2. Change only the `commit=` line in `upstream.lock` and the Docker build-argument
   default to the same full hash.
3. Run `make build-backend-native GOLDENDICT_NG_SOURCE=/path/to/worktree`.
   Missing/renamed source files, header changes, or new library requirements
   should fail here and be handled explicitly in `CMakeLists.txt` or the narrow
   shims.
4. Run real fixtures for every enabled format, including MDX with a companion
   MDD, compressed DSL, and StarDict. Verify metadata and `mainPath`, exact
   lookup, prefix suggestions, article-internal links, representative resources,
   missing-resource behavior, and index reuse on a second start.
5. Run the HTTP/frontend integration suite so the public REST contract remains
   unchanged. Record any new runtime packages and image-size change.
6. Commit the lock, source-list/shim changes, and fixture-test evidence together.

Never add a broad upstream include directory ahead of `shims/`, silently enable
desktop subsystems, or copy upstream parser code into this repository. A small,
explicit adapter surface is what makes the next GoldenDict-ng upgrade quick to
audit and easy to roll back.
