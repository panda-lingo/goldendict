import { describe, expect, it } from "vitest";
import {
  classifyArticleLink,
  resolveResourceUrl,
  type ResourceContext,
} from "../src/renderer/link-router";

const context: ResourceContext = {
  apiBaseUrl: "/api/v1",
  dictionaryId: "dict id",
  resourceBaseUrl: "/api/v1/dictionaries/dict%20id/resources",
};

describe("article link and resource routing", () => {
  it("converts GoldenDict resource schemes to HTTP routes", () => {
    expect(resolveResourceUrl("bres://dict%20id/images/a b.png", context)).toBe(
      "/api/v1/dictionaries/dict%20id/resources/images/a%20b.png",
    );
    expect(classifyArticleLink("gdau://dict%20id/sound.mp3", context)).toEqual({
      kind: "audio",
      url: "/api/v1/dictionaries/dict%20id/resources/sound.mp3",
    });
    expect(resolveResourceUrl("gico://dict%20id/dicticon.png", context)).toContain(
      "document.png",
    );
  });

  it("preserves root-relative backend routes instead of appending resourceBaseUrl", () => {
    expect(resolveResourceUrl("/api/v1/resources/already-routed.png", context)).toBe(
      "/api/v1/resources/already-routed.png",
    );
    expect(
      resolveResourceUrl("/api/v1/resources/already-routed.png", {
        ...context,
        apiBaseUrl: "https://dictionary.example/api/v1",
      }),
    ).toBe("https://dictionary.example/api/v1/resources/already-routed.png");
  });

  it("extracts lookup words, anchors, and dictionary filters", () => {
    expect(
      classifyArticleLink(
        "gdlookup://localhost/word?gdanchor=section&dictionaries=a,b",
        context,
      ),
    ).toEqual({
      kind: "lookup",
      word: "word",
      anchor: "section",
      dictionaryIds: ["a", "b"],
    });
    expect(classifyArticleLink("bword:another%20word", context)).toMatchObject({
      kind: "lookup",
      word: "another word",
    });
  });

  it("blocks desktop-only and executable internal schemes", () => {
    expect(classifyArticleLink("gdprg://program/run", context)).toEqual({
      kind: "unsafe",
    });
    expect(classifyArticleLink("javascript:alert(1)", context)).toEqual({
      kind: "unsafe",
    });
    expect(classifyArticleLink("vbscript:msgbox(1)", context)).toEqual({
      kind: "unsafe",
    });
    expect(classifyArticleLink("unknown-handler:payload", context)).toEqual({
      kind: "unsafe",
    });
  });
});
