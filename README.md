# GoldenDict Web

GoldenDict Web turns local dictionary files into a small REST service and a
reusable, brandable web renderer. It keeps GoldenDict-ng's article structure,
format-specific CSS, display presets, internal links, media, and resource
behavior without embedding Qt in the consuming application.

The repository contains three independently usable pieces:

- `backend/` — a dictionary-only FastAPI service. Its default image embeds the
  headless GoldenDict-ng C++ worker and scans configured local paths at startup.
  There is no file-upload endpoint.
- `packages/frontend/` — the framework-independent
  `@panda-lingo/goldendict` package and `<goldendict-view>` custom
  element.
- `demo/` — a real consumer of the package public API with dictionary,
  display-preset, light/dark, and custom-brand controls.

## Supported dictionary files

The backend compiles and invokes GoldenDict-ng's complete file-backed local
factory set at the pinned commit, in upstream load order:

- BGL, StarDict, LSA, DSL, DictD, XDXF, SDict, and Aard
- ZipSounds, MDict/MDX, GLS, SLOB, ZIM, and EPWING

Companion files and resources are interpreted by the original GoldenDict-ng
C++ implementations. The FastAPI process is only the stable HTTP/protocol
gateway; it contains no Python dictionary readers and does not parse a file
when the native worker fails or declines it.

The frontend bundles GoldenDict-ng's complete base article stylesheet, so its
format-specific article classes remain available even as more backend adapters
are added. See [backend/README.md](backend/README.md) for exact reader behavior
and current limitations.

## Run the API and demo

### Use the published release

`compose.published.yaml` pulls the released multi-architecture API image from
GHCR and builds the demo as an independent consumer of the released npm
package. It does not compile GoldenDict-ng or copy `packages/frontend` into the
demo image.

```bash
GOLDENDICT_DICTIONARY_PATH=/absolute/path/to/dictionaries \
  docker compose -f compose.published.yaml up --build --pull always
```

Open <http://localhost:5173>. The API is also available at
<http://localhost:8080/api/v1>. `GOLDENDICT_RELEASE` selects the matching
container and npm package version and defaults to `0.1.8`; for example:

```bash
GOLDENDICT_RELEASE=0.1.8 \
GOLDENDICT_DICTIONARY_PATH=/absolute/path/to/dictionaries \
  docker compose -f compose.published.yaml up --build
```

Use `GOLDENDICT_DEMO_PORT` or `GOLDENDICT_API_PORT` to change the host ports.
The dictionary directory remains a read-only bind mount, and native indexes are
kept in the Compose-managed `published-native-indices` volume.
The npm consumer image is rebuilt by Compose, so updating the API cannot
silently leave an older local demo image running. Its OCI version label records
the selected `GOLDENDICT_RELEASE`.

If a dictionary header renders but its article falls back to plain browser
headings and bullet lists, the lookup succeeded but one or more dictionary
sidecars did not. Check the browser Network panel for the exact nested resource
routes; each must return its asset rather than a proxy's HTML error page:

```text
/api/v1/dictionaries/<id>/resources/<dictionary>.css
/api/v1/dictionaries/<id>/resources/<dictionary>.js
```

CSS must be served as `text/css` and JavaScript as `text/javascript`. A reverse
proxy must forward the complete `/api/*` path, must not impose
`Cross-Origin-Resource-Policy: same-origin`, and must preserve literal `null` in
`GOLDENDICT_CORS_ORIGINS` so fonts and dictionary fetch/XHR work from the
opaque-origin sandbox. Confirm the deployed backend with
`GET /api/v1/health` (`version` should match `GOLDENDICT_RELEASE`).
The demo changes the article state to `error` and displays the failed stylesheet
or script URL instead of silently labelling the degraded rendering `Ready`.

### Build from source

The quickest path uses Docker Compose. Point it at a directory that already
contains dictionaries and, when it is not in the default repository-adjacent
location, a GoldenDict-ng checkout at the commit pinned by this project.
Compose supplies that checkout as the named `goldendict-ng` build context. The
dictionary directory is mounted read-only and scanned when the API starts;
nothing is uploaded or copied through the REST API.

```bash
GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng \
GOLDENDICT_DICTIONARY_PATH=/absolute/path/to/dictionaries \
  docker compose up --build
```

Open <http://localhost:5173>. The API is also exposed at
<http://localhost:8080/api/v1>, with OpenAPI UI at
<http://localhost:8080/docs>.

For the fixture available in this workspace:

```bash
GOLDENDICT_NG_SOURCE=/home/ubuntu/goldendict-ng \
GOLDENDICT_DICTIONARY_PATH=/home/ubuntu/speak/examples/dict \
  docker compose up --build
```

The default `api` service is the only runtime. It combines the thin FastAPI
gateway with the GoldenDict-ng worker, keeps native indices in the
`native-indices` volume, and remains unready if native startup fails. To build
that image without starting Compose:

```bash
make build-backend-native \
  GOLDENDICT_NG_SOURCE=/absolute/path/to/goldendict-ng
```

This produces `goldendict-api:native`.

The Make target goes through `backend/native/build.sh`. That wrapper supports
ordinary and linked Git worktrees, verifies the locked commit, and records a
deterministic dirty flag plus SHA-256 of relevant local GoldenDict-ng source
changes in the worker's ready metadata. Intentional local patches remain
buildable; set `GOLDENDICT_NG_REQUIRE_CLEAN=ON` for a strict release/CI build.

To develop the browser packages without Compose:

```bash
npm ci
npm run dev
```

The demo defaults to same-origin `/api/v1`. During Vite development its proxy
targets `http://localhost:8080`; the API base can also be changed in the demo.

## REST API

The stable versioned surface is intentionally limited to dictionary operations:

```text
GET    /api/v1/health
GET    /api/v1/dictionaries?language=en&source_language=en&target_language=fr
GET    /api/v1/lookup/{word}?dictionary_ids=id1,id2
GET    /api/v1/suggestions?prefix=hel&limit=20
GET    /api/v1/dictionaries/{id}/resources/{path}
```

The catalog is immutable after startup. Changing mounted dictionaries requires
restarting the service so GoldenDict-ng can rebuild and atomically publish the
catalog.

```bash
curl http://localhost:8080/api/v1/dictionaries
curl 'http://localhost:8080/api/v1/dictionaries?language=en'
curl http://localhost:8080/api/v1/lookup/hello
```

Each dictionary can have its own optional JSON metadata file. Append `.json`
to the complete main filename—for example, `oaldpe.mdx` uses
`oaldpe.mdx.json`:

```json
{
  "name": "My Oxford Learner's Dictionary",
  "sourceLanguage": "en",
  "targetLanguage": "zh-Hant"
}
```

Fields may be omitted. For either language, omission, `null`, or `"auto"`
keeps the value detected by GoldenDict-ng from the dictionary. The per-file
JSON name takes precedence over GoldenDict-ng's optional directory-level
`metadata.toml` name. Language tags are case-insensitive and `_` is accepted
as a separator; public responses use lowercase hyphenated tags.

The `language` catalog filter matches either source or target. The directional
`source_language` and `target_language` filters can be combined, and `en`
also matches a more specific tag such as `en-US`.

## Frontend package

Install or depend on `@panda-lingo/goldendict`, then configure its API client
and theme. The package does not require React, Vue, or another framework.

```ts
import {
  DictionaryClient,
  defineGoldendictView,
} from "@panda-lingo/goldendict";

defineGoldendictView();

const view = document.querySelector("goldendict-view");
view.client = new DictionaryClient({
  baseUrl: "https://dictionary.example/api/v1",
});
const suggestions = await view.client.suggestions("exam", { limit: 20 });
const englishDictionaries = await view.client.listDictionaries({
  language: "en",
});
view.theme = {
  brandName: "Acme Lexicon",
  preset: "modern",
  mode: "auto",
  tokens: {
    accentColor: "#6d3bea",
    linkColor: "#4f46e5",
    headerColor: "#f0edff",
  },
};
await view.lookup("example");
```

The configured `baseUrl` is also the resource-routing boundary. A reverse
proxy may therefore mount the unmodified API at `/api/v1/mdict`; backend-rooted
`/api/v1/...` article assets are resolved through that configured mount rather
than escaping to the origin root.

The component emits cancelable lookup/media/external-link events and state,
active-article, and collapse events. Dictionary content is rendered in a
sandboxed, opaque-origin iframe. The default `sandboxed` script policy retains
GoldenDict-ng script-dependent behavior without granting dictionary content
same-origin access to the host page. Consumers can choose `scriptPolicy =
"none"` as a strict script-removal policy. Layout is a separate choice:
`layoutMode = "fidelity"` preserves GoldenDict-ng and dictionary-authored
geometry and is the default. `"responsive"` is an explicit opt-in that adds
fixed-width browser safeguards for narrow containers.

For a trusted local dictionary that depends on sidecars and should retain the
native GoldenDict cascade:

```ts
view.layoutMode = "fidelity";
view.scriptPolicy = "sandboxed";
```

For example, OALDPE articles retain their `bres://.../oaldpe.js` and
`bres://.../oaldpe-jquery.js` script references. The REST resource route serves
those local sidecars as `text/javascript` with
`X-Content-Type-Options: nosniff`. They execute by default, confined to the
opaque-origin iframe. Set `scriptPolicy = "none"` to remove dictionary scripts
and inline handlers. Matching GoldenDict-ng layout also requires `layoutMode =
"fidelity"`; JavaScript permission alone does not alter the CSS cascade. Such
an iframe sends an Origin of `null` for XHR/fetch. The bundled demo and reusable
component both default to sandboxed scripts plus fidelity layout so their
locally mounted dictionaries match GoldenDict-ng. The Compose demo permits
`http://localhost:5173,null` so sandboxed dictionary
JavaScript can request its resources; enable the `null` CORS origin only in
deployments that intentionally use this opaque-origin sandbox behavior. The
backend's general default CORS setting remains unchanged.

Full package usage is in
[packages/frontend/README.md](packages/frontend/README.md). The demo imports
only this public package entry—it contains no duplicate renderer.

## GoldenDict-ng upgrades

Rendering assets and compatibility behavior are pinned to GoldenDict-ng commit
`5ad66765aa423d381025566bff990f7d8007be84`. Vendored CSS/icons have a manifest
and checksums. Refresh them from any newer or locally modified checkout with:

```bash
npm run sync:goldendict --workspace @panda-lingo/goldendict -- \
  --source /path/to/goldendict-ng
npm test
npm run build
```

Handwritten browser adapters are outside the generated/vendor boundary. The
native backend compiles an explicit manifest containing every local file-format
factory from the same pinned checkout and exposes it through a version-neutral
subprocess protocol. See the
[native worker guide](backend/native/README.md) and
[backend/upstream-compatibility.yaml](backend/upstream-compatibility.yaml).
See
[UPGRADING_GOLDENDICT.md](packages/frontend/UPGRADING_GOLDENDICT.md) for the
review workflow.

## Verify

```bash
make verify
```

That runs frontend checksum contracts, package tests, type checking,
production package/demo builds, and the gateway's Dockerized test suite.

After building `goldendict-api:native`, the native protocol smoke test generates
tiny DSL and StarDict bundles locally, then verifies startup metadata and
`mainPath`, lookup HTML, and prefix suggestions, and reports the ready event's
upstream commit/dirty provenance without requiring copyrighted dictionary
fixtures. It also starts the combined image and requires the FastAPI health
contract to become ready without startup errors:

```bash
make test-native-worker
```

The browser fidelity gate builds the package and demo, starts a deterministic
HTTP dictionary fixture, and exercises it in real Chromium. It verifies the
GoldenDict-compatible runtime, authored layout geometry, cacheable sidecar
CSS/JavaScript, a second lookup in a fresh iframe, and stable CSS-pixel geometry
at both 1x and 1.5x device scale:

```bash
npx playwright install --with-deps --no-shell chromium
npm run test:e2e
```

The repository also includes an explicit real-dictionary gate. It is never
silently skipped: point it at a running demo backed by an OALDPE fixture, and
optionally override the API URL when the demo cannot use its normal proxy:

```bash
GOLDENDICT_E2E_URL=http://localhost:5173 \
GOLDENDICT_E2E_API_URL=http://localhost:8080/api/v1 \
  npm run test:e2e:real
```

GoldenDict fidelity is measured in CSS pixels. Operating-system display scale,
browser device-pixel ratio, and GoldenDict's own zoom determine the physical
pixel size of a screenshot; compare captures at the same viewport and device
scale rather than hard-coding a dictionary zoom into the renderer.

## CI and releases

The [GitHub Actions workflow](.github/workflows/ci-release.yml) runs on pull
requests, pushes to `main`, and manual dispatches. It type-checks, tests, and
builds the frontend package and demo; runs the deterministic Chromium fidelity
and consecutive-lookup gate; runs the Dockerized REST-gateway suite; and builds
and smoke-tests the combined native image on native `linux/amd64` and
`linux/arm64` GitHub runners. The GoldenDict-ng repository and commit must agree
across the native lock, backend compatibility map, and frontend asset manifest,
and the checked-in browser assets are compared with that exact upstream
checkout. The copyrighted real-dictionary fixture remains an explicit local
gate rather than a CI dependency.

Publishing starts only when a GitHub Release is published. Before creating it,
set the same SemVer in `package.json`, `packages/frontend/package.json`,
`demo/package.json`, `backend/pyproject.toml`, and `backend/app/__init__.py`, then
use the exact tag `vX.Y.Z` or `vX.Y.Z-prerelease`; a suffixed version must also
be marked as a GitHub prerelease. The workflow publishes:

- `ghcr.io/panda-lingo/goldendict` as one `linux/amd64` + `linux/arm64`
  manifest, with version, major/minor, commit, and—only for a stable
  release—`latest` tags. Each architecture is built natively, pushed by digest,
  and smoke-tested before the tags are created. The final manifest is checked
  for both architectures and receives a GitHub build-provenance attestation.
- `@panda-lingo/goldendict` to the public npm registry. Stable releases use
  the `latest` npm dist-tag and GitHub prereleases use `next`. The private demo
  workspace is built but never published.

GHCR uses the workflow's short-lived `GITHUB_TOKEN`; no registry secret is
needed. GitHub initially makes a new container package private, so make it
public in the package settings after the first push when this repository is
public.

For the package's first-ever publication, when it does not yet exist on npm,
provide a one-time granular npm automation token with access to the
`@panda-lingo` scope in the `NPM_TOKEN` organization secret. After that first
publish, configure the package's npm Trusted Publisher with organization/user
`panda-lingo`, repository `goldendict`, workflow filename `ci-release.yml`, and
the `npm publish` action. Then remove `NPM_TOKEN`; the same job uses GitHub OIDC
(`id-token: write`) and npm-generated provenance without a long-lived publish
credential. A rerun safely skips an npm version that already exists.

## License

This project is GPL-3.0-or-later because it includes and adapts GoldenDict-ng
rendering assets and behavior. See [LICENSE](LICENSE), [NOTICE](NOTICE), and the
frontend package's [third-party notices](packages/frontend/THIRD_PARTY_NOTICES.md).
Dictionary data is not included and retains its own copyright and license.
