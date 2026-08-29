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
      theme: { preset: "modern" },
    });

    expect(html).toContain('class="gdarticle"');
    expect(html).toContain('class="gddictname"');
    expect(html).toContain('class="gdarticlebody gdlangfrom-en"');
    expect(html).toContain('data-gd-action="lookup"');
    expect(html).toContain("Content-Security-Policy");
    expect(html).toMatch(
      /class="gddicticon"><img src="(?:data:image\/png;base64,|\/src\/assets\/icons\/document\.png)/,
    );
    expect(html).not.toContain("/dictionaries/fixture/icon");
    expect(html).not.toMatch(/(?:qrc|bres|gico|gdau|gdvideo|gdlookup|bword):/);
  });
});
