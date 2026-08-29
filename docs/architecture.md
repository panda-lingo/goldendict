# Architecture

GoldenDict Web separates dictionary parsing from browser rendering while
preserving GoldenDict-ng's article HTML contract.

```text
mounted dictionary bundle -> GoldenDict-ng format factories -> JSONL worker
                                                             |
                                                             v
consumer app <- @goldendict-web/frontend <- stable REST gateway
       |                                             |
       +-------- sandboxed article document <--------+
```

The default image compiles GoldenDict-ng's real `Mdx`, `Dsl`, and `Stardict`
factories into a headless worker. FastAPI is a thin process/protocol and HTTP
boundary, not a second dictionary parser. It scans read-only configured roots
once at startup, publishes an immutable catalog, performs lookup and prefix
suggestion, and serves bundle resources. There is no upload route. A separate
Python-only image remains available as a graceful fallback; its optional
server-path load/unload routes are disabled by default.

The frontend package owns the GoldenDict-compatible article wrapper,
display-style presets, collapse and active-article behavior, internal lookup
navigation, and package states. Consumers customize those states and wrapper
chrome through CSS tokens and theme configuration. Dictionary-authored HTML is
rendered in an isolated document so it cannot style the host application.

## Browser URL boundary

GoldenDict-ng uses Qt-only schemes (`bres:`, `gdau:`, `gdvideo:`, `gico:`,
`gdlookup:`, and `qrc:`). The native worker returns canonical article HTML
unchanged. The frontend URL router translates those schemes to versioned HTTP
resource routes, package assets, or typed browser events before the browser
network layer sees them. CSS resources are rewritten at the gateway boundary.

## Trust boundary

Dictionary files and their HTML are untrusted input. Local paths are restricted
to configured roots; resource names are normalized and cannot traverse those
roots. The renderer strips dictionary JavaScript by default. Its explicit
`sandboxed` compatibility policy retains scripts in an opaque-origin iframe
without same-origin access to the host; such script fetches carry `Origin:
null`, which deployments must allow deliberately.

## Fidelity source

Wrapper markup, article behavior, and compatibility styling follow
GoldenDict-ng commit `5ad66765aa423d381025566bff990f7d8007be84`, notably
`src/article_maker.cc`, `src/scripts/gd-builtin.js`,
`src/stylesheets/article-style.css`, and format-specific readers under
`src/dict/`. The worker lock, selected source list, provenance digest, shims, and
upgrade gates are documented in [backend/native/README.md](../backend/native/README.md).
See [NOTICE](../NOTICE) for attribution.
