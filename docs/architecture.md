# Architecture

GoldenDict Web separates the native dictionary engine from browser delivery
without introducing a second parser.

```text
read-only dictionary roots
          |
          v
all GoldenDict-ng local factories -> shared native catalog/indexes
          |                              |
          | batched article + prefix work|
          v                              v
JSON-lines worker -> thin FastAPI REST/resource gateway
                              |
                              v
             @panda-lingo/goldendict iframe renderer
                              |
                              v
                         consumer app
```

The worker compiles all fourteen file-backed local factories from the pinned
GoldenDict-ng checkout. FastAPI validates roots, owns worker lifecycle, maps the
native catalog to HTTP, and enforces resource response limits; it contains no
dictionary-format implementation. Catalog publication is immutable after
startup. There is no upload, runtime load/unload, or alternate parser path.

Lookup is batched once across the selected catalog. The C++ worker overlaps
GoldenDict-ng's shared synonym resolution with prefix work, then launches all
selected article requests before waiting, allowing upstream thread-pool work,
decompression, and I/O to overlap. Native deferred
initialization begins after catalog construction so MDX and DSL readers warm
before the first query.

## Browser URL boundary

GoldenDict-ng emits Qt schemes such as `bres:`, `gdau:`, `gdvideo:`, `gico:`,
`gdlookup:`, and `qrc:`. The worker returns that canonical article HTML
unchanged. The frontend router translates it to versioned resource URLs,
bundled upstream assets, or typed navigation/media events. CSS resources are
rewritten only at the HTTP resource boundary. Dictionary header icons are
rendered from upstream `Dictionary::getIcon()` and served as native PNG
resources.

## Trust boundary

Dictionary files and HTML are untrusted. Roots and direct filesystem sidecars
are canonicalized; unsafe resource segments and out-of-bundle symlinks are
rejected. The selected-source MDX guard repeats containment checks after every
MDD redirect.

The renderer uses an opaque-origin iframe. Its default `sandboxed` policy
preserves script-dependent GoldenDict-ng behavior without granting host
same-origin access; `scriptPolicy = "none"` is the strict script-removal mode.
Sandboxed XHR/fetch requests use `Origin: null`, which deployments must allow
deliberately.

## Fidelity source

The default frontend layout is GoldenDict fidelity: the exact pinned base,
print, and display-preset stylesheets load without the optional responsive
override layer. Wrapper markup and interactions track
`src/article_maker.cc` and `src/scripts/gd-builtin.js`; article fragments,
resources, language metadata, and icons come directly from the same native
checkout.

All behavior is pinned to GoldenDict-ng commit
`5ad66765aa423d381025566bff990f7d8007be84`. See the
[native worker guide](../backend/native/README.md),
[compatibility map](../backend/upstream-compatibility.yaml), and
[NOTICE](../NOTICE).
