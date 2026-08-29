import type {
  GoldenDictTheme,
  GoldenDictThemeTokens,
  ThemeMode,
} from "../types";

export const LIGHT_THEME_TOKENS: Readonly<GoldenDictThemeTokens> = {
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Ubuntu, Arial, sans-serif',
  textColor: "#222222",
  mutedTextColor: "#555555",
  linkColor: "#005a9c",
  backgroundColor: "#ffffff",
  surfaceColor: "#f9f9f9",
  headerColor: "#ddeeff",
  borderColor: "#e3e3e3",
  accentColor: "#cc0000",
  selectionColor: "#cc0000",
  selectionTextColor: "#ffffff",
  radius: "8px",
  spacing: "8px",
};

export const DARK_THEME_TOKENS: Readonly<GoldenDictThemeTokens> = {
  fontFamily: LIGHT_THEME_TOKENS.fontFamily,
  textColor: "#edf1f5",
  mutedTextColor: "#aeb8c3",
  linkColor: "#79bfff",
  backgroundColor: "#16191d",
  surfaceColor: "#20252b",
  headerColor: "#283746",
  borderColor: "#3c4652",
  accentColor: "#ff6b6b",
  selectionColor: "#b43a45",
  selectionTextColor: "#ffffff",
  radius: "8px",
  spacing: "8px",
};

export function resolveThemeMode(mode: ThemeMode = "light"): "light" | "dark" {
  if (mode !== "auto") {
    return mode;
  }
  return globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function declaration(name: string, value: string | undefined): string {
  return value === undefined ? "" : `${name}:${value};`;
}

export function escapeStyleText(css: string): string {
  return css.replace(/<\/style/gi, "<\\/style");
}

export function themeToCss(theme: GoldenDictTheme = {}): string {
  const mode = resolveThemeMode(theme.mode);
  const supplied = theme.tokens ?? {};
  const tokens: Partial<GoldenDictThemeTokens> =
    mode === "dark" ? { ...DARK_THEME_TOKENS, ...supplied } : supplied;
  const variables = [
    declaration("--gd-font-family", tokens.fontFamily),
    declaration("--gd-text-color", tokens.textColor),
    declaration("--gd-muted-text-color", tokens.mutedTextColor),
    declaration("--gd-link-color", tokens.linkColor),
    declaration("--gd-background-color", tokens.backgroundColor),
    declaration("--gd-surface-color", tokens.surfaceColor),
    declaration("--gd-header-color", tokens.headerColor),
    declaration("--gd-border-color", tokens.borderColor),
    declaration("--gd-accent-color", tokens.accentColor),
    declaration("--gd-selection-color", tokens.selectionColor),
    declaration("--gd-selection-text-color", tokens.selectionTextColor),
    declaration("--gd-radius", tokens.radius),
    declaration("--gd-spacing", tokens.spacing),
  ].join("");
  const optionalRules = [
    tokens.fontFamily ? "body{font-family:var(--gd-font-family);}" : "",
    tokens.textColor
      ? "body{color:var(--gd-text-color);--text-color:var(--gd-text-color);}"
      : "",
    tokens.mutedTextColor
      ? "body{--secondary-text-color:var(--gd-muted-text-color);}"
      : "",
    tokens.linkColor
      ? "body{--link-color:var(--gd-link-color);}a{color:var(--gd-link-color);}"
      : "",
    tokens.backgroundColor
      ? "html,body,.gdarticle{background-color:var(--gd-background-color);}"
      : "",
    tokens.surfaceColor
      ? ".gddictname{background:var(--gd-surface-color);}"
      : "",
    tokens.headerColor
      ? ".gddictname{background:var(--gd-header-color);}"
      : "",
    tokens.borderColor
      ? ".gdarticle,.gddictname{border-color:var(--gd-border-color);}"
      : "",
    tokens.accentColor
      ? ".gdactivearticle{border-color:var(--gd-accent-color);}"
      : "",
    tokens.selectionColor || tokens.selectionTextColor
      ? "::selection{background:var(--gd-selection-color,var(--selection-bg));color:var(--gd-selection-text-color,var(--selection-text));}"
      : "",
    tokens.radius ? ".gdarticle{border-radius:var(--gd-radius);}" : "",
  ].join("");

  return escapeStyleText(
    `:root{color-scheme:${mode};${variables}}${optionalRules}${theme.cssText ?? ""}`,
  );
}
