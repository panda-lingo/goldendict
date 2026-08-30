import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const fixtureDirectory = dirname(fileURLToPath(import.meta.url));
const staticRoot = resolve(fixtureDirectory, "../demo/dist");
const host = "127.0.0.1";
const port = Number.parseInt(process.env.GOLDENDICT_E2E_PORT ?? "4173", 10);
const dictionaryId = "synthetic-fidelity";
const resourceRoot = `/api/v1/dictionaries/${dictionaryId}/resources`;
const resourceRequests = new Map();

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

const fixtureCss = String.raw`
  .fixture-snapshot {
    color: #333;
    font: 15px/21px Georgia, "Times New Roman", serif;
  }

  .fixture-nav {
    display: flex;
    gap: 8px;
    margin-bottom: 7px;
  }

  .fixture-nav span {
    border-radius: 5px;
    padding: 3px 10px;
    color: #285f2a;
    background: #b8ddb9;
    font: 600 13px/18px Arial, sans-serif;
  }

  .fixture-nav .active {
    color: white;
    background: #4b8b45;
  }

  .oald {
    display: none;
    margin-bottom: 1em;
  }

  .oald.visible {
    display: block;
  }

  .entry > .top-container::before {
    content: "";
    display: block;
    height: 1.5em;
    border: 1px solid #a5d6a7;
    border-bottom: 0;
    border-radius: 8px 8px 0 0;
    background: #e0f2e0;
  }

  .entry > .top-container .webtop {
    position: relative;
    box-sizing: content-box;
    min-height: 70px;
    margin-bottom: 1em;
    padding: 8px 12px 12px;
    border: 1px solid #a5d6a7;
    border-radius: 0 0 8px 8px;
    box-shadow: 0 4px 8px rgb(0 0 0 / 10%);
  }

  .fixture-headword {
    margin-right: 4px;
    color: #0672ce;
    font-size: 24px;
    line-height: 30px;
  }

  .fixture-pos {
    color: #d36b20;
    font-style: italic;
  }

  .fixture-phonetics {
    display: block;
    margin-top: 4px;
    color: #0072cf;
    font-family: "Segoe UI", sans-serif;
  }

  .fixture-definition {
    margin: 0 0 6px;
  }

  .fixture-definition::first-letter {
    color: #e00028;
    font-style: italic;
  }

  .fixture-example {
    margin: 3px 0 3px 20px;
    color: #666;
    font-style: italic;
  }

  .fixture-metric-box {
    box-sizing: content-box;
    width: 240px;
    margin-top: 12px;
    padding: 8px 20px;
    border-left: 2px solid #9fd8ff;
    color: #0672ce;
    background: #f0f8ff;
    font: 600 14px/20px Arial, sans-serif;
  }

  .oaldpe-config-gear__icon {
    position: absolute;
    top: 8px;
    right: 8px;
    display: grid;
    box-sizing: content-box;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 50%;
    color: #006ebf;
    background: repeating-linear-gradient(45deg, #c5e5fa 0 3px, #eef8ff 3px 6px);
    font: 700 11px/30px Arial, sans-serif;
  }
`;

const jqueryFixture = String.raw`
  (() => {
    const ready = (callback) => {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", callback, { once: true });
      } else {
        queueMicrotask(callback);
      }
    };
    globalThis.jQuery = ready;
    globalThis.$ = ready;
  })();
`;

const sidecarFixture = String.raw`
  (() => {
    const atLoad = Object.freeze({
      dictionaryName: globalThis.__DICT__?.name ?? null,
      userAgent: navigator.userAgent,
    });
    globalThis.__goldendictFixtureAtLoad = atLoad;
    globalThis.jQuery(() => {
      for (const root of document.querySelectorAll(".fixture-snapshot")) {
        const executions = Number(root.dataset.sidecarExecutions ?? "0") + 1;
        root.dataset.sidecarExecutions = String(executions);
        root.dataset.runtime = atLoad.dictionaryName === "GoldenDict" ? "goldendict" : "browser";
        const entry = root.querySelector(".oald");
        entry?.classList.add("visible");
        const webtop = root.querySelector(".webtop");
        if (webtop && !webtop.querySelector(".oaldpe-config-gear__icon")) {
          const gear = document.createElement("span");
          gear.className = "oaldpe-config-gear__icon";
          gear.textContent = "O10";
          gear.setAttribute("aria-hidden", "true");
          webtop.prepend(gear);
        }
        root.dataset.ready = "true";
      }
    });
  })();
`;

function articleHtml(word) {
  const resourceVersion = encodeURIComponent(word);
  const description =
    word === "hello"
      ? "used as a greeting when you meet somebody or answer the phone"
      : "something that shows, explains, or supports what you say";
  const example =
    word === "hello"
      ? "Hello, is there anybody there?"
      : "This is a clear example of the authored dictionary layout.";
  return `<gd-section-html><gd-section-head>
    <link rel="stylesheet" href="${resourceRoot}/fidelity.css?lookup=${resourceVersion}">
    <script src="${resourceRoot}/fixture-jquery.js?lookup=${resourceVersion}"></script>
    <script src="${resourceRoot}/fixture-sidecar.js?lookup=${resourceVersion}"></script>
  </gd-section-head><gd-section-body>
    <div class="fixture-snapshot oaldpe" data-fixture-word="${word}">
      <nav class="fixture-nav"><span class="active">Entry</span><span>Usage</span><span>All</span></nav>
      <div class="oald oald-entry-root">
        <div class="entry"><div class="top-container"><div class="webtop">
          <strong class="fixture-headword headword">${word}</strong><span class="fixture-pos">noun</span>
          <span class="fixture-phonetics">/${word === "hello" ? "həˈləʊ" : "ɪɡˈzɑːmpl"}/</span>
        </div></div></div>
        <p class="fixture-definition">1 ${description}</p>
        <p class="fixture-example">${example}</p>
        <div class="fixture-metric-box">GoldenDict-authored content-box geometry</div>
      </div>
    </div>
  </gd-section-body></gd-section-html>`;
}

function json(response, statusCode, value) {
  const body = Buffer.from(`${JSON.stringify(value)}\n`);
  response.writeHead(statusCode, {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
    "Content-Length": body.length,
    "Content-Type": "application/json; charset=utf-8",
  });
  response.end(body);
}

function text(response, contentType, body, cache = false) {
  const value = Buffer.from(body);
  response.writeHead(200, {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": cache ? "public, max-age=3600, immutable" : "no-store",
    "Content-Length": value.length,
    "Content-Type": contentType,
    "X-Content-Type-Options": "nosniff",
  });
  response.end(value);
}

function lookupPayload(word) {
  return {
    word,
    articles: [
      {
        dictionaryId,
        dictionaryName: "Synthetic Fidelity Dictionary",
        format: "mdict",
        html: articleHtml(word),
        sourceLanguage: "en",
        targetLanguage: "en",
        resourceBaseUrl: `${resourceRoot}/`,
      },
    ],
    suggestions: [],
    lookupTimeMs: 3,
  };
}

async function serveStatic(pathname, response) {
  let relativePath = pathname === "/" ? "index.html" : decodeURIComponent(pathname).replace(/^\/+/, "");
  let candidate = resolve(staticRoot, relativePath);
  if (candidate !== staticRoot && !candidate.startsWith(`${staticRoot}${sep}`)) {
    response.writeHead(400).end();
    return;
  }
  try {
    if (!(await stat(candidate)).isFile()) {
      throw new Error("not a file");
    }
  } catch {
    if (extname(relativePath)) {
      response.writeHead(404).end();
      return;
    }
    candidate = resolve(staticRoot, "index.html");
    relativePath = "index.html";
  }
  const metadata = await stat(candidate);
  response.writeHead(200, {
    "Cache-Control": "no-store",
    "Content-Length": metadata.size,
    "Content-Type": contentTypes.get(extname(relativePath)) ?? "application/octet-stream",
  });
  createReadStream(candidate).pipe(response);
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", `http://${host}:${port}`);
    if (url.pathname === "/__fixture/health") {
      text(response, "text/plain; charset=utf-8", "ready\n");
      return;
    }
    if (url.pathname === "/favicon.ico") {
      response.writeHead(204).end();
      return;
    }
    if (url.pathname === "/__fixture/stats") {
      json(response, 200, Object.fromEntries(resourceRequests));
      return;
    }
    if (url.pathname === "/__fixture/reset") {
      resourceRequests.clear();
      json(response, 200, { reset: true });
      return;
    }
    if (url.pathname === "/api/v1/dictionaries") {
      json(response, 200, [
        {
          id: dictionaryId,
          name: "Synthetic Fidelity Dictionary",
          format: "mdict",
          wordCount: 2,
          sourceLanguage: "en",
          targetLanguage: "en",
          resourceBaseUrl: `${resourceRoot}/`,
        },
      ]);
      return;
    }
    if (url.pathname.startsWith("/api/v1/lookup/")) {
      const word = decodeURIComponent(url.pathname.slice("/api/v1/lookup/".length));
      json(response, 200, lookupPayload(word));
      return;
    }
    if (url.pathname.startsWith(`${resourceRoot}/`)) {
      const name = url.pathname.slice(resourceRoot.length + 1);
      resourceRequests.set(name, (resourceRequests.get(name) ?? 0) + 1);
      if (name === "fidelity.css") {
        text(response, "text/css; charset=utf-8", fixtureCss);
        return;
      }
      if (name === "fixture-jquery.js") {
        text(response, "text/javascript; charset=utf-8", jqueryFixture);
        return;
      }
      if (name === "fixture-sidecar.js") {
        text(response, "text/javascript; charset=utf-8", sidecarFixture);
        return;
      }
    }
    await serveStatic(url.pathname, response);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    json(response, 500, { error: message });
  }
});

server.listen(port, host);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
