# GoldenDict-ng native worker

This directory builds a headless JSON-lines worker from the pinned
GoldenDict-ng source checkout. It is the sole dictionary implementation behind
the public REST gateway; this repository does not maintain parallel parsers.

## Upstream scope

The executable compiles every file-backed local factory called by the pinned
`LoadDictionaries::handlePath()` implementation, in the same order:

```text
Bgl, Stardict, Lsa, Dsl, DictdFiles, Xdxf, Sdict, Aard,
ZipSounds, Mdx, Gls, Slob, Zim, Epwing
```

This covers BGL, StarDict, LSA, DSL, DictD, XDXF, SDict, Aard, ZipSounds,
MDict, GLS, SLOB, ZIM, and EPWING. Their parsing, native indexes, matching,
article HTML, companion resources, icons, and deferred initialization are
upstream C++ behavior. Sound directories, Hunspell, websites/network sources,
programs, and transliterations are configuration-backed providers rather than
mounted dictionary formats and are intentionally outside this service.

Mounted roots use GoldenDict-ng's recursive filename filters and skip
`.dsl.files` resource trees. Factories are constructed once over that ordered
file catalog for startup efficiency, then published in the same recursive
directory/factory order as `LoadDictionaries::handlePath()`.

The bridge targets GoldenDict-ng's `Dictionary::Class` and individual factory
interfaces instead of linking the desktop `loadDictionaries` orchestrator.
That orchestrator requires widgets, application configuration, network
managers, initialization UI, message boxes, and other desktop services. The
explicit factory manifest keeps the headless boundary small and makes upstream
interface drift fail at compile time.

Headers in `shims/` replace only desktop service boundaries unused by local
headword lookup, such as application configuration, UI broadcasting, FTS UI,
and audio-link UI registration. The worker uses `QGuiApplication` with the
offscreen QPA backend because upstream dictionary icons can use `QPixmap`; the
exact format-icon assets referenced by those factories are embedded under their
upstream resource paths. Generated MDX icon abbreviations and TIFF conversion
also use the pinned upstream implementations.

## Security adaptation

`cmake/prepare_mdx_source.cmake` creates the compiled copy of upstream
`mdx.cc` and replaces only `loadResourceFile` with a canonical
dictionary-directory guard. The guard runs for direct sidecars and every MDD
`@@@LINK` redirect. It preserves nested, case-sensitive resources while
rejecting dot traversal and symlinks outside the bundle. Exact source anchors
must match once or configuration fails, and `resource-guard-test` runs during
every image build.

## Pin and provenance

[`upstream.lock`](upstream.lock) records the required checkout commit.
[`cmake/verify_upstream.cmake`](cmake/verify_upstream.cmake) verifies the lock,
effective Git commit, dirty state, and source digest before dependency probing
or compilation. [`provenance.sh`](provenance.sh) uses a disposable Git index to
hash a canonical binary diff of all worker inputs under `src/` and `icons/`.
It includes tracked changes/deletions and untracked
generated inputs without touching the developer's real index.
`build.sh` then stages only those attested inputs into Docker's named context,
avoiding repeated transfer of the upstream checkout's `.git` object database.
Direct Compose builds instead inspect the checkout through a read-only,
non-persistent BuildKit mount before compiling the same source-only layer.

The ready event publishes `upstreamCommit`, `upstreamDirty`, and
`upstreamDiffSha256`. Intentional local changes remain buildable and attested;
release/CI builds set `GOLDENDICT_NG_REQUIRE_CLEAN=ON`.

## Build and run

Build the combined API image:

```bash
make build-backend-native \
  GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng
```

Build only the worker image:

```bash
backend/native/build.sh /absolute/path/to/goldendict-ng
```

The latter produces `goldendict-native-worker:dev`. Run it with read-only
dictionary data and a writable index directory owned by UID 10001:

```bash
docker run --rm -i \
  --mount type=bind,src=/absolute/dictionaries,dst=/dictionaries,readonly \
  goldendict-native-worker:dev
```

Executable options are:

```text
goldendict-native-worker \
  --dictionary-root PATH [--dictionary-root PATH ...] \
  [--index-dir PATH] [--timeout-ms N]
```

Index/load progress goes to stderr. Stdout is reserved for protocol messages.
EOF on stdin shuts the process down.

Build dependencies include Qt 6 Core/Concurrent/Gui/Svg/Widgets/Xml, fmt,
zlib, bzip2, liblzma, liblzo2, libvorbisfile, libzim, GNU libeb, toml++, and
iconv. The runtime also installs the Qt offscreen QPA and image-format plugins.
New or stale native indices can make initial startup slow; later starts reuse
the writable index directory. Adjacent `metadata.toml` name and FTS overrides
are applied through GoldenDict-ng's own metadata implementation.

## Protocol

Each stdin/stdout line is one compact JSON object. The first stdout message is
the ready event:

```json
{
  "event": "ready",
  "upstreamCommit": "5ad66765aa423d381025566bff990f7d8007be84",
  "upstreamDirty": false,
  "upstreamDiffSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "supportedFormats": [
    "bgl", "stardict", "lsa", "dsl", "dictd", "xdxf", "sdict",
    "aard", "zipsounds", "mdx", "gls", "slob", "zim", "epwing"
  ],
  "dictionaries": []
}
```

Dictionary metadata includes `id`, `name`, `format`, `wordCount`, language
codes, `mainPath`, and `iconResourcePath`. The icon resource is the PNG emitted
by upstream `Dictionary::getIcon()`, including custom dictionary icons.

Requests preserve a caller-chosen `id` and receive either an `ok` result or a
stable error object:

```json
{"id":"1","op":"list"}
{"id":"2","op":"lookup","word":"hello","dictionaryIds":["id"],"suggestionLimit":20}
{"id":"3","op":"suggestions","prefix":"hel","limit":20,"dictionaryIds":["id"]}
{"id":"4","op":"resource","dictionaryId":"id","path":"style.css"}
```

One lookup overlaps shared synonym resolution with prefix work, then starts all
selected article requests before consuming results. This restores
GoldenDict-ng-style coordination and parser overlap while removing the former
per-dictionary protocol round trips. MDX and DSL deferred initialization starts
immediately after catalog construction.

The worker returns canonical article fragments, not browser-rewritten HTML.
The REST/frontend layers translate `bres:`, `gico:`, `gdlookup:`, `gdau:`,
`gdvideo:`, and `qrc:` at their respective boundaries.

## Verification and upgrades

```bash
make test-native-worker \
  GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng
```

The gate compiles the full source manifest and dependencies, runs the C++
resource guard, asserts the fourteen-format ready contract, generates DSL and
StarDict fixtures, and verifies metadata, lookup, suggestions, native PNG
icons, resource traversal rejection, and combined API startup.

Treat every pin change as a compatibility change:

1. Check out the candidate commit in a clean worktree.
2. Update `upstream.lock` and the frontend compatibility manifest together.
3. Build with `GOLDENDICT_NG_REQUIRE_CLEAN=ON` and resolve every source,
   interface, shim, Qt, or library change explicitly.
4. Run representative fixtures for all available formats, including companion
   and compressed/split resources.
5. Run the REST and real-browser fidelity gates, then record runtime dependency
   and image-size changes.

Do not copy parser implementations locally or place a broad upstream include
directory ahead of `shims/`. A compile-time-explicit boundary is what keeps the
next upgrade auditable.
