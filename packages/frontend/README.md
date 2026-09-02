# @panda-lingo/goldendict

Framework-independent client and `<goldendict-view>` renderer for the
GoldenDict REST service. The package preserves GoldenDict-ng article markup and
styles inside a sandboxed iframe while exposing typed browser events and brand
theme tokens.

```ts
import {
  DictionaryClient,
  defineGoldendictView,
} from "@panda-lingo/goldendict";

defineGoldendictView();
const view = document.querySelector("goldendict-view");
view.client = new DictionaryClient({ baseUrl: "/api/v1" });
await view.lookup("example");
```

`baseUrl` is the complete public API mount, including a reverse-proxy prefix
when one exists. GoldenDict-rooted article resources are rebased through that
mount, so a host can expose the service at a route such as `/api/v1/mdict`
without rewriting lookup payloads:

```ts
view.client = new DictionaryClient({ baseUrl: "/api/v1/mdict" });
```

Search-first hosts can request bounded prefix suggestions through the same
client and API base before committing an article lookup:

```ts
const result = await view.client.suggestions("exam", { limit: 20 });
console.log(result.suggestions);
```

Dictionary discovery can be filtered by either language or by translation
direction. Filters map to the backend's `language`, `source_language`, and
`target_language` query parameters:

```ts
const dictionaries = await view.client.listDictionaries({
  sourceLanguage: "en",
  targetLanguage: "fr",
});
```

The earlier `listDictionaries(abortSignal)` form remains supported; new code
can instead pass the signal together with filters as `listDictionaries({
language: "en", signal })`.

Importing the package registers `<goldendict-view>` automatically. Call
`defineGoldendictView("my-dictionary-view")` when a custom tag name is useful.

The component fills the width of its containing layout, uses container-aware
host chrome, and remeasures article height whenever its iframe reflows. Article
layout defaults to GoldenDict fidelity: the pinned upstream body margin,
content-box model, dictionary header flow, and dictionary-authored CSS cascade
remain intact.

The optional responsive mode adds a browser override layer that constrains
legacy fixed-width media, makes wide tables and preformatted text locally
scrollable, unwraps common floated wiki panels on narrow screens, and keeps
article headers usable with coarse pointers. Script permission is independent:
a dictionary may require both fidelity layout and sandboxed sidecar JavaScript.

```ts
view.layoutMode = "responsive";
view.scriptPolicy = "sandboxed";
```

The default `layoutMode` is `"fidelity"`. Consumers can opt into the browser
safeguards with `layout-mode="responsive"` on the custom element.

Compare at the same CSS viewport, device scale, and GoldenDict zoom: those host
browser settings still affect physical pixel size and line wrapping.

```css
.dictionary-column {
  min-width: 0;
}

goldendict-view {
  width: 100%;
  max-width: 72rem;
  margin-inline: auto;
}
```

Consumer `theme.cssText` is emitted after the responsive layer and can override
it when a particular dictionary requires different behavior. Set
`--gd-responsive-gutter` there to customize the article's fluid inner spacing.

The public API includes:

- `DictionaryClient` for dictionary listing, prefix suggestions, and lookup.
- `GoldenDictView` and `defineGoldendictView` for framework-independent use.
- `GoldenDictTheme`, light/dark token presets, and `themeToCss` for branding.
- `GOLDENDICT_EVENTS` for lookup, active article, collapse, media, external-link,
  dictionary-resource failure, and state notifications.
- Resource/link helpers for hosts that need to inspect GoldenDict URLs.

Dictionary scripts are retained by default (`scriptPolicy = "sandboxed"`)
inside the iframe, which never gets `allow-same-origin`. Set the policy to
`"none"` to remove scripts and inline handlers. Lookup, media, and external-link
events are cancelable so a host application can replace the default navigation
behavior.

The bundled demo and reusable component both default to `"sandboxed"` scripts
for locally mounted dictionaries, so script-dependent formats such as OALDPE
retain their interactions. `"fidelity"` is likewise the default layout.

In sandboxed mode, external sidecars such as `bres://.../Dictionary-UI.js` are
routed through the article's `resourceBaseUrl` without changing filename case.
Because the iframe has an opaque origin, dictionary XHR/fetch requests send
`Origin: null`; the read-only API must explicitly allow that origin when this
compatibility mode is enabled. Classic script element loads do not grant the
dictionary access to the host document.

Failed external dictionary stylesheets and scripts are not treated as a
successful render. The component keeps the article visible, changes
`state` to `"error"`, exposes the failures through `view.resourceErrors`, and
emits `GOLDENDICT_EVENTS.resourceError` with the failed URL and resource type:

```ts
view.addEventListener(GOLDENDICT_EVENTS.resourceError, (event) => {
  const { detail } = event as CustomEvent;
  console.error("Dictionary sidecar failed", detail);
});
```

This diagnoses top-level `<link rel="stylesheet">` and `<script src>` failures;
font/image failures and exceptions thrown inside dictionary code remain normal
browser console/network diagnostics.

Run the package demo from the workspace root with `npm run dev`. It discovers
the dictionaries loaded from the backend's configured local paths at startup.

GoldenDict-ng CSS and icons are pinned and sync-managed. See
[`UPGRADING_GOLDENDICT.md`](./UPGRADING_GOLDENDICT.md) for the one-command local
checkout upgrade flow.
