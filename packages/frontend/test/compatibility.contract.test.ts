import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BUILTIN_ASSET_URLS } from "../src/assets";
import {
  GOLDENDICT_BASE_CSS,
  getGoldenDictPresetCss,
} from "../src/styles/fidelity";
import {
  GOLDENDICT_SCHEME_SUPPORT,
  classifyArticleLink,
  resolveResourceUrl,
} from "../src/renderer/link-router";
import type { GoldenDictPreset } from "../src/types";

describe("pinned GoldenDict-ng compatibility contract", () => {
  it("pins every vendored source file and checksum", async () => {
    const manifestPath = resolve(
      process.cwd(),
      "compatibility/goldendict-ng.json",
    );
    const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as {
      sourceRepository: string;
      sourceCommit: string;
      sourceDirty: boolean;
      sourceDiffSha256: string;
      files: Array<{ source: string; target: string; sha256: string }>;
    };
    expect(manifest.sourceRepository).toMatch(/^https:\/\//);
    expect(manifest.sourceCommit).toMatch(/^[a-f0-9]{40}$/);
    expect(typeof manifest.sourceDirty).toBe("boolean");
    expect(manifest.sourceDiffSha256).toMatch(/^[a-f0-9]{64}$/);
    expect(manifest.files.length).toBeGreaterThanOrEqual(20);
    for (const entry of manifest.files) {
      expect(entry.source).not.toBe("");
      expect(entry.target).not.toBe("");
      expect(entry.sha256).toMatch(/^[a-f0-9]{64}$/);
    }
  });

  it("keeps required wrapper and dictionary-format selectors", () => {
    const compatibilityCss = [
      GOLDENDICT_BASE_CSS,
      getGoldenDictPresetCss("classic"),
      getGoldenDictPresetCss("modern"),
      getGoldenDictPresetCss("lingvo"),
      getGoldenDictPresetCss("babylon"),
      getGoldenDictPresetCss("lingoes"),
      getGoldenDictPresetCss("lingoes-blue"),
    ].join("\n");
    for (const selector of [
      ".gdarticle",
      ".gddictname",
      ".gdarticlebody",
      ".gdcollapsedarticle",
      ".gdstemmedsuggestion",
      ".dsl_article",
      ".sdct_h",
      ".xdxf_def",
      ".mdict",
      ".zimdict",
      ".epwing_article",
      ".mwiki",
    ]) {
      expect(compatibilityCss).toContain(selector);
    }
  });

  it("accounts for all article presets and referenced built-in assets", () => {
    const presets: GoldenDictPreset[] = [
      "default",
      "classic",
      "modern",
      "lingvo",
      "babylon",
      "lingoes",
      "lingoes-blue",
    ];
    for (const preset of presets.filter((value) => value !== "default")) {
      expect(getGoldenDictPresetCss(preset).length).toBeGreaterThan(50);
    }
    const compatibilityCss = [
      GOLDENDICT_BASE_CSS,
      ...presets.map((preset) => getGoldenDictPresetCss(preset)),
    ].join("\n");
    for (const asset of [
      "warning.svg",
      "playsound.svg",
      "video.svg",
      "arrow.svg",
      "downarrow.svg",
      "expand_opt.svg",
      "collapse_opt.svg",
      "expand_article.svg",
      "collapse_article.svg",
      "old-arrow.svg",
      "old-downarrow.svg",
    ]) {
      expect(BUILTIN_ASSET_URLS[asset]).toMatch(/^data:/);
    }
    expect(compatibilityCss).not.toContain("qrc:///icons/");
  });

  it("explicitly routes or rejects every GoldenDict Qt article scheme", () => {
    expect(Object.keys(GOLDENDICT_SCHEME_SUPPORT).sort()).toEqual(
      [
        "ankicard",
        "ankisearch",
        "bres",
        "bword",
        "entry",
        "gdau",
        "gdinternal",
        "gdlookup",
        "gico",
        "gdprg",
        "gdtts",
        "gdvideo",
        "qrc",
        "qrcx",
      ].sort(),
    );
    const context = { apiBaseUrl: "/api/v1", dictionaryId: "fixture" };
    expect(resolveResourceUrl("bres://fixture/a.png", context)).toMatch(/^\/api\/v1\//);
    expect(classifyArticleLink("gdlookup://localhost/word", context).kind).toBe(
      "lookup",
    );
    expect(classifyArticleLink("gdprg://fixture/run", context).kind).toBe(
      "unsafe",
    );
  });
});
