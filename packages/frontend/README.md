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

Importing the package registers `<goldendict-view>` automatically. Call
`defineGoldendictView("my-dictionary-view")` when a custom tag name is useful.

The component is responsive by default. It fills the width of its containing
layout, uses container-aware host chrome, and remeasures article height whenever
its iframe reflows. A separate browser override layer constrains legacy
fixed-width dictionary media, makes wide tables and preformatted text locally
scrollable, unwraps common floated wiki panels on narrow screens, and keeps
article headers usable with coarse pointers. The pinned GoldenDict-ng CSS stays
unchanged so upstream updates remain straightforward.

For GoldenDict-compatible article geometry, select the fidelity layout. This
omits the browser override layer so the upstream body margin, content-box model,
dictionary header flow, and dictionary-authored CSS cascade remain intact.
Script permission is independent: a dictionary may require both fidelity layout
and sandboxed sidecar JavaScript.

```ts
view.layoutMode = "fidelity";
view.scriptPolicy = "sandboxed";
```

The default `layoutMode` is `"responsive"`; the bundled demo deliberately uses
`"fidelity"` so it can be compared directly with GoldenDict-ng. Consumers can
also set `layout-mode="fidelity"` on the custom element.

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

- `DictionaryClient` for dictionary listing and lookup, plus the backend's
  explicitly opt-in server-path load operation.
- `GoldenDictView` and `defineGoldendictView` for framework-independent use.
- `GoldenDictTheme`, light/dark token presets, and `themeToCss` for branding.
- `GOLDENDICT_EVENTS` for lookup, active article, collapse, media, external-link,
  dictionary-resource failure, and state notifications.
- Resource/link helpers for hosts that need to inspect GoldenDict URLs.

Dictionary scripts are removed by default (`scriptPolicy = "none"`). The
explicit `"sandboxed"` policy retains them inside the iframe, which never gets
`allow-same-origin`. Lookup, media, and external-link events are cancelable so a
host application can replace the default navigation behavior.

The bundled demo deliberately selects `"sandboxed"` scripts and `"fidelity"`
layout for locally mounted dictionaries so script-dependent formats such as
OALDPE render with their GoldenDict typography, geometry, and interactions.
These demo choices do not change the component defaults (`"none"` scripts and
`"responsive"` layout) for consumers.

In sandboxed mode, external sidecars such as `bres://.../Dictionary-UI.js` are
routed through the article's `resourceBaseUrl` without changing filename case.
Because the iframe has an opaque origin, dictionary XHR/fetch requests send
`Origin: null`; the read-only API must explicitly allow that origin when this
compatibility mode is enabled. Classic script element loads do not grant the
dictionary access to the host document.

Failed external dictionary stylesheets and scripts are not treated as a
successful render. The component keeps the fallback article visible, changes
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
