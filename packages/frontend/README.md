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
  and state notifications.
- Resource/link helpers for hosts that need to inspect GoldenDict URLs.

Dictionary scripts are removed by default (`scriptPolicy = "none"`). The
explicit `"sandboxed"` policy retains them inside the iframe, which never gets
`allow-same-origin`. Lookup, media, and external-link events are cancelable so a
host application can replace the default navigation behavior.

The bundled demo deliberately selects `"sandboxed"` for locally mounted
dictionaries so script-dependent formats such as OALDPE render with their full
GoldenDict typography and interactions. This demo choice does not change the
component's safer `"none"` default for consumers.

In sandboxed mode, external sidecars such as `bres://.../Dictionary-UI.js` are
routed through the article's `resourceBaseUrl` without changing filename case.
Because the iframe has an opaque origin, dictionary XHR/fetch requests send
`Origin: null`; the read-only API must explicitly allow that origin when this
compatibility mode is enabled. Classic script element loads do not grant the
dictionary access to the host document.

Run the package demo from the workspace root with `npm run dev`. It discovers
the dictionaries loaded from the backend's configured local paths at startup.

GoldenDict-ng CSS and icons are pinned and sync-managed. See
[`UPGRADING_GOLDENDICT.md`](./UPGRADING_GOLDENDICT.md) for the one-command local
checkout upgrade flow.
