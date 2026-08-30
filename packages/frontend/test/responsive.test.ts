import { describe, expect, it } from "vitest";
import { GOLDENDICT_RESPONSIVE_CSS } from "../src/styles/responsive";

describe("responsive article safeguards", () => {
  it("constrains legacy fixed-width content without changing vendored CSS", () => {
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("--gd-responsive-gutter");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain(
      ".gdarticlebody > :where(div, section, article, aside, header, footer, figure)",
    );
    expect(GOLDENDICT_RESPONSIVE_CSS).not.toContain(
      ".gdarticlebody :where(div, section, article, aside, header, footer, figure)",
    );
    expect(GOLDENDICT_RESPONSIVE_CSS).toMatch(
      /img, picture, video, canvas, svg, iframe, object, embed/,
    );
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("max-inline-size: 100% !important");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain(".gdarticlebody table");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("overflow-x: auto");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("overflow-wrap: anywhere");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain(".gddictname:focus-visible");
  });

  it("does not collapse nested div-based dictionary controls", () => {
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain(
      ".gdarticlebody > :where(div, section, article, aside, header, footer, figure)",
    );
    expect(GOLDENDICT_RESPONSIVE_CSS).not.toContain(
      ".gdarticlebody :where(div, section, article, aside, header, footer, figure)",
    );
  });

  it("provides compact and coarse-pointer layouts", () => {
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("@media (max-width: 64rem)");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("@media (max-width: 40rem)");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("@media (pointer: coarse)");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("min-block-size: 2.75rem");
    expect(GOLDENDICT_RESPONSIVE_CSS).toContain("float: none !important");
  });
});
