import { describe, expect, it } from "vitest";
import { buildArticleDocument } from "../src/renderer/article-document";
import type { LookupResponse } from "../src/types";

const response: LookupResponse = {
  word: "test",
  articles: [
    {
      dictionaryId: "fixture",
      dictionaryName: "Fixture dictionary",
      format: "dsl",
      sourceLanguage: "en",
      targetLanguage: "ar",
      html: '<div class="dsl_article"><a href="bword:next">next</a><img src="qrc:///icons/playsound.svg"></div>',
    },
  ],
  suggestions: ["tested"],
  lookupTimeMs: 1,
};

describe("buildArticleDocument", () => {
  it("emits GoldenDict wrapper classes and browser-safe assets", () => {
    const html = buildArticleDocument(response, {
      apiBaseUrl: "/api/v1",
      instanceId: "test-instance",
      scriptPolicy: "none",
      theme: {
        preset: "modern",
        cssText: "/* consumer-responsive-override */",
      },
    });

    expect(html).toContain('class="gdarticle"');
    expect(html).toContain('class="gddictname"');
    expect(html).toContain('class="gdarticlebody gdlangfrom-en"');
    expect(html).toContain('data-gd-action="lookup"');
    expect(html).toContain("Content-Security-Policy");
    expect(html).toContain('data-gd-style="responsive"');
    expect(html).toContain("@media (max-width: 40rem)");
    expect(html).toContain("resizeObserver.observe(document.body)");
    expect(html).toContain("if(height===lastHeight)return");
    expect(html).toContain('addEventListener("resize",requestSize');
    expect(html.indexOf('data-gd-style="responsive"')).toBeLessThan(
      html.indexOf("consumer-responsive-override"),
    );
    expect(html).toMatch(
      /class="gddicticon"><img src="(?:data:image\/png;base64,|\/src\/assets\/icons\/document\.png)/,
    );
    expect(html).not.toContain("/dictionaries/fixture/icon");
    expect(html).not.toMatch(/(?:qrc|bres|gico|gdau|gdvideo|gdlookup|bword):/);
  });

  it("propagates the resolved host theme to theme-aware dictionary sidecars", () => {
    const html = buildArticleDocument(response, {
      apiBaseUrl: "/api/v1",
      instanceId: "dark-theme-instance",
      scriptPolicy: "sandboxed",
      theme: { mode: "dark" },
    });

    expect(html).toContain('<html data-gd-theme="dark"');
    expect(html).toContain('data-darkreader-scheme="dark"');
    expect(html).toContain('"themeMode":"dark"');
    expect(html).toContain('document.querySelectorAll(".oaldpe")');
    expect(html).toContain(
      'attributeFilter:["data-theme","data-darkreader-scheme"]',
    );
  });

  it("installs the GoldenDict runtime identity before dictionary sidecars", () => {
    const sidecarMarker = "globalThis.__observedDictionaryHost=globalThis.__DICT__";
    const html = buildArticleDocument(
      {
        ...response,
        articles: [
          {
            ...response.articles[0]!,
            html: `<script>${sidecarMarker}</script><p>article</p>`,
          },
        ],
      },
      {
        apiBaseUrl: "/api/v1",
        instanceId: "runtime-identity-instance",
        scriptPolicy: "sandboxed",
      },
    );

    expect(html).toContain('data-gd-runtime="compatibility"');
    expect(html).toContain('globalThis.__DICT__={name:"GoldenDict",version:"web"}');
    expect(html).toContain('addEventListener("error",(event)=>{');
    expect(html).toContain('target instanceof HTMLLinkElement');
    expect(html).toContain('target instanceof HTMLScriptElement');
    expect(html).toContain('link.sheet!==null');
    expect(html).toContain('post("resource-error"');
    expect(html.indexOf("globalThis.__DICT__=")).toBeLessThan(
      html.indexOf(sidecarMarker),
    );
    expect(html.indexOf('__GOLDENDICT_WEB_RESOURCE_ERRORS__=pending')).toBeLessThan(
      html.indexOf(sidecarMarker),
    );
  });

  it("offers a GoldenDict fidelity layout without browser override CSS", () => {
    const html = buildArticleDocument(response, {
      apiBaseUrl: "/api/v1",
      instanceId: "fidelity-instance",
      scriptPolicy: "sandboxed",
      layoutMode: "fidelity",
    });

    expect(html).toContain('data-gd-layout="fidelity"');
    expect(html).not.toContain('data-gd-style="responsive"');
    expect(html).toContain('style="display:block" id="gd-fixture"');
    expect(html).toContain('<div style="clear:both;" aria-hidden="true"></div>');
  });
});
