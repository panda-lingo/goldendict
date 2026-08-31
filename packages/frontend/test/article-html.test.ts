import { describe, expect, it } from "vitest";
import type { LookupArticle } from "../src/types";
import { prepareArticleHtml } from "../src/renderer/article-html";

function article(html: string): LookupArticle {
  return {
    dictionaryId: "dict-1",
    dictionaryName: "Fixture",
    format: "mdx",
    html,
    resourceBaseUrl: "/api/v1/dictionaries/dict-1/resources",
  };
}

describe("prepareArticleHtml", () => {
  it("honors backend data-gd media annotations before relative-link lookup rules", () => {
    const html = prepareArticleHtml(
      article(
        '<a href="/api/v1/dictionaries/dict-1/resources/sound.mp3" data-gd-audio>Play</a>',
      ),
      "/api/v1",
      "none",
    );
    const container = document.createElement("div");
    container.innerHTML = html;
    const anchor = container.querySelector("a");

    expect(anchor?.getAttribute("data-gd-action")).toBe("audio");
    expect(anchor?.getAttribute("href")).toBe(
      "/api/v1/dictionaries/dict-1/resources/sound.mp3",
    );
    expect(html).not.toContain("resources/api/v1");
  });

  it("honors the backend data-gd-action resource annotation", () => {
    const html = prepareArticleHtml(
      article(
        '<a href="/api/v1/dictionaries/dict-1/resources/guide.pdf" data-gd-action="resource">Guide</a>',
      ),
      "https://dictionary.example/api/v1",
      "none",
    );
    const container = document.createElement("div");
    container.innerHTML = html;
    const anchor = container.querySelector("a");

    expect(anchor?.getAttribute("data-gd-action")).toBe("resource");
    expect(anchor?.getAttribute("href")).toBe(
      "https://dictionary.example/api/v1/dictionaries/dict-1/resources/guide.pdf",
    );
  });

  it("resolves every backend resource surface against a cross-origin API", () => {
    const html = prepareArticleHtml(
      article(`
        <link rel="stylesheet" href="/api/v1/dictionaries/dict-1/resources/theme.css">
        <img src="/api/v1/dictionaries/dict-1/resources/picture.png"
          srcset="/api/v1/dictionaries/dict-1/resources/small.png 1x, relative.png 2x">
        <div style="background:url('/api/v1/dictionaries/dict-1/resources/bg.png')"></div>
        <style>.icon{background:url(relative.svg)}</style>
      `),
      "https://dictionary.example/api/v1",
      "none",
    );

    expect(html).toContain(
      'href="https://dictionary.example/api/v1/dictionaries/dict-1/resources/theme.css"',
    );
    expect(html).toContain(
      'src="https://dictionary.example/api/v1/dictionaries/dict-1/resources/picture.png"',
    );
    expect(html).toContain(
      "https://dictionary.example/api/v1/dictionaries/dict-1/resources/small.png 1x",
    );
    expect(html).toContain(
      "https://dictionary.example/api/v1/dictionaries/dict-1/resources/relative.png 2x",
    );
    expect(html).toContain(
      "https://dictionary.example/api/v1/dictionaries/dict-1/resources/bg.png",
    );
    expect(html).toContain(
      "https://dictionary.example/api/v1/dictionaries/dict-1/resources/relative.svg",
    );
  });

  it("rewrites custom resources and removes scripts under the strict none policy", () => {
    const html = prepareArticleHtml(
      article(
        '<img src="bres://dict-1/image.png" onerror="alert(1)"><script>alert(1)</script>',
      ),
      "/api/v1",
      "none",
    );

    expect(html).toContain(
      'src="/api/v1/dictionaries/dict-1/resources/image.png"',
    );
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<script");
  });

  it("retains and routes local dictionary scripts under the sandboxed policy", () => {
    const source =
      '<script src="bres://dict-1/Dictionary-UI.js"></script><script>globalThis.fixture=true</script>';
    const html = prepareArticleHtml(
      article(source),
      "/api/v1",
      "sandboxed",
    );
    expect(html).toContain("globalThis.fixture=true");
    expect(html).toContain(
      'src="/api/v1/dictionaries/dict-1/resources/Dictionary-UI.js"',
    );

    expect(prepareArticleHtml(article(source), "/api/v1", "none")).not.toContain(
      "<script",
    );
  });
});
