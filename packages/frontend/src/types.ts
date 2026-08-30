export type GoldenDictPreset =
  | "default"
  | "classic"
  | "modern"
  | "lingvo"
  | "babylon"
  | "lingoes"
  | "lingoes-blue";

export type ThemeMode = "light" | "dark" | "auto";

export type ScriptPolicy = "none" | "sandboxed";

/**
 * `fidelity` preserves GoldenDict-ng and dictionary-authored layout without
 * the package's responsive override stylesheet.
 * `responsive` adds browser safeguards for legacy fixed-width article content.
 */
export type ArticleLayoutMode = "fidelity" | "responsive";

export type ViewState =
  | "idle"
  | "loading"
  | "ready"
  | "not-found"
  | "error";

export interface DictionarySummary {
  id: string;
  name: string;
  format: string;
  sourceLanguage?: string;
  targetLanguage?: string;
  path?: string;
  iconUrl?: string;
  resourceBaseUrl?: string;
  wordCount?: number;
}

export interface LoadDictionaryRequest {
  path: string;
  name?: string;
}

export interface LoadDictionaryResponse {
  dictionary: DictionarySummary;
  loaded: boolean;
  message?: string;
}

export interface LookupArticle {
  dictionaryId: string;
  dictionaryName: string;
  format: string;
  html: string;
  sourceLanguage?: string;
  targetLanguage?: string;
  iconUrl?: string;
  resourceBaseUrl?: string;
}

export interface LookupResponse {
  word: string;
  articles: LookupArticle[];
  suggestions: string[];
  lookupTimeMs: number;
}

export interface LookupOptions {
  dictionaryIds?: readonly string[];
  signal?: AbortSignal;
}

export interface DictionaryClientOptions {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
  headers?: Readonly<Record<string, string>>;
  credentials?: RequestCredentials;
}

export interface GoldenDictThemeTokens {
  fontFamily: string;
  textColor: string;
  mutedTextColor: string;
  linkColor: string;
  backgroundColor: string;
  surfaceColor: string;
  headerColor: string;
  borderColor: string;
  accentColor: string;
  selectionColor: string;
  selectionTextColor: string;
  radius: string;
  spacing: string;
}

export interface GoldenDictTheme {
  preset?: GoldenDictPreset;
  mode?: ThemeMode;
  tokens?: Partial<GoldenDictThemeTokens>;
  cssText?: string;
  brandName?: string;
  logoUrl?: string;
}

export interface LookupEventDetail {
  word: string;
  anchor?: string;
  dictionaryIds?: string[];
}

export interface ActiveArticleEventDetail {
  dictionaryId: string;
}

export interface ArticleToggleEventDetail {
  dictionaryId: string;
  collapsed: boolean;
}

export interface MediaRequestEventDetail {
  kind: "audio" | "video" | "resource";
  url: string;
  dictionaryId?: string;
}

export interface ExternalLinkEventDetail {
  url: string;
}

export type DictionaryResourceType = "stylesheet" | "script";

/** A dictionary-authored stylesheet or script that the article could not load. */
export interface DictionaryResourceErrorEventDetail {
  resourceType: DictionaryResourceType;
  url: string;
  dictionaryId?: string;
}

export interface ViewStateEventDetail {
  state: ViewState;
  word?: string;
  error?: Error;
}

export const GOLDENDICT_EVENTS = {
  lookup: "goldendict-lookup",
  activeArticleChange: "goldendict-active-article-change",
  articleToggle: "goldendict-article-toggle",
  mediaRequest: "goldendict-media-request",
  externalLink: "goldendict-external-link",
  resourceError: "goldendict-resource-error",
  stateChange: "goldendict-state-change",
} as const;
