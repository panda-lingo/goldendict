import { describe, expect, it, vi } from "vitest";
import {
  DARK_THEME_TOKENS,
  resolveThemeMode,
  themeToCss,
} from "../src/renderer/theme";

describe("theme helpers", () => {
  it("generates scoped GoldenDict token overrides", () => {
    const css = themeToCss({
      mode: "light",
      tokens: { accentColor: "#123456", headerColor: "#abcdef" },
    });
    expect(css).toContain("--gd-accent-color:#123456");
    expect(css).toContain("background:var(--gd-header-color)");
  });

  it("uses complete safe defaults for dark mode", () => {
    const css = themeToCss({ mode: "dark" });
    expect(css).toContain(DARK_THEME_TOKENS.backgroundColor);
    expect(css).toContain("color-scheme:dark");
  });

  it("resolves auto mode from matchMedia", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    expect(resolveThemeMode("auto")).toBe("dark");
    vi.unstubAllGlobals();
  });
});
