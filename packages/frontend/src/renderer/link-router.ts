import { resolveBuiltinAsset } from "../assets";

export interface ResourceContext {
  apiBaseUrl: string;
  dictionaryId: string;
  iconUrl?: string;
  resourceBaseUrl?: string;
}

export type ArticleLinkAction =
  | { kind: "anchor"; anchor: string }
  | { kind: "lookup"; word: string; anchor?: string; dictionaryIds?: string[] }
  | { kind: "audio" | "video" | "resource"; url: string }
  | { kind: "external"; url: string }
  | { kind: "unsafe" };

const CUSTOM_RESOURCE_SCHEMES = new Set([
  "bres",
  "qrcx",
  "gico",
  "gdau",
  "gdvideo",
]);

const API_ROUTE_PREFIX = "/api/v1";

export const GOLDENDICT_SCHEME_SUPPORT = {
  gdlookup: "lookup",
  bword: "lookup",
  entry: "lookup",
  bres: "resource",
  qrcx: "resource",
  gico: "resource",
  gdau: "audio",
  gdvideo: "video",
  qrc: "asset",
  gdprg: "unsupported",
  gdtts: "unsupported",
  gdinternal: "unsupported",
  ankicard: "unsupported",
  ankisearch: "unsupported",
} as const;

const UNSUPPORTED_INTERNAL_SCHEMES = new Set(
  Object.entries(GOLDENDICT_SCHEME_SUPPORT)
    .filter(([, support]) => support === "unsupported")
    .map(([scheme]) => scheme),
);

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function joinUrl(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

function normalizedResourcePath(url: URL): string {
  return url.pathname
    .replace(/^\/+/, "")
    .split("/")
    .map((part) => encodeURIComponent(decode(part)))
    .join("/");
}

function absoluteOrRelativeUrl(raw: string, base: string): string {
  if (/^[a-z][a-z\d+.-]*:/i.test(raw) || raw.startsWith("//")) {
    return raw;
  }
  if (/^[a-z][a-z\d+.-]*:/i.test(base)) {
    return new URL(raw, base.endsWith("/") ? base : `${base}/`).toString();
  }
  return joinUrl(base, raw);
}

function routeThroughConfiguredApi(raw: string, apiBaseUrl: string): string {
  const normalizedApiBase = apiBaseUrl
    .replace(/[?#].*$/, "")
    .replace(/\/+$/, "");
  if (
    (raw === API_ROUTE_PREFIX || raw.startsWith(`${API_ROUTE_PREFIX}/`)) &&
    normalizedApiBase !== ""
  ) {
    return `${normalizedApiBase}${raw.slice(API_ROUTE_PREFIX.length)}`;
  }
  if (/^[a-z][a-z\d+.-]*:/i.test(apiBaseUrl)) {
    return new URL(raw, apiBaseUrl).toString();
  }
  return raw;
}

function contextResourceBase(context: ResourceContext): string | undefined {
  const base = context.resourceBaseUrl;
  if (!base) {
    return undefined;
  }
  if (base.startsWith("/") && !base.startsWith("//")) {
    return routeThroughConfiguredApi(base, context.apiBaseUrl);
  }
  return base;
}

export function resolveResourceUrl(
  rawUrl: string,
  context: ResourceContext,
): string {
  const builtin = resolveBuiltinAsset(rawUrl);
  if (builtin) {
    return builtin;
  }
  if (rawUrl.startsWith("/") && !rawUrl.startsWith("//")) {
    return routeThroughConfiguredApi(rawUrl, context.apiBaseUrl);
  }
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    const resourceBase = contextResourceBase(context);
    return resourceBase
      ? absoluteOrRelativeUrl(rawUrl, resourceBase)
      : rawUrl;
  }
  const scheme = url.protocol.slice(0, -1).toLowerCase();
  if (!CUSTOM_RESOURCE_SCHEMES.has(scheme)) {
    return rawUrl;
  }
  const dictionaryId = url.hostname || context.dictionaryId;
  if (scheme === "gico") {
    return context.iconUrl
      ? resolveResourceUrl(context.iconUrl, {
          ...context,
          iconUrl: undefined,
        })
      : (resolveBuiltinAsset("qrc:///icons/document.png") ?? "");
  }
  const path = normalizedResourcePath(url);
  const defaultBase = `${context.apiBaseUrl.replace(/\/+$/, "")}/dictionaries/${encodeURIComponent(dictionaryId)}/resources`;
  const resolved = joinUrl(contextResourceBase(context) ?? defaultBase, path);
  return url.hash ? `${resolved}${url.hash}` : resolved;
}

function parseLookupUrl(rawUrl: string): ArticleLinkAction | undefined {
  const schemeMatch = /^([a-z][a-z\d+.-]*):(.*)$/i.exec(rawUrl);
  if (!schemeMatch) {
    return undefined;
  }
  const scheme = schemeMatch[1]?.toLowerCase();
  if (scheme !== "gdlookup" && scheme !== "bword" && scheme !== "entry") {
    return undefined;
  }
  let word = "";
  let anchor: string | undefined;
  let dictionaryIds: string[] | undefined;
  try {
    const parsed = new URL(rawUrl);
    word = parsed.searchParams.get("word") ?? parsed.pathname.replace(/^\/+/, "");
    anchor =
      parsed.searchParams.get("gdanchor") ??
      (parsed.hash.slice(1) || undefined);
    const dictionaries = parsed.searchParams.get("dictionaries");
    dictionaryIds = dictionaries?.split(",").filter(Boolean);
    if (!word && (scheme === "bword" || scheme === "entry")) {
      word = parsed.hostname;
    }
  } catch {
    const remainder = schemeMatch[2]?.replace(/^\/{0,2}/, "") ?? "";
    const [pathAndQuery, hash] = remainder.split("#", 2);
    const [path, query] = (pathAndQuery ?? "").split("?", 2);
    word = path ?? "";
    const params = new URLSearchParams(query ?? "");
    anchor = params.get("gdanchor") ?? (hash || undefined);
  }
  word = decode(word.replace(/^\/+/, ""));
  if (!word) {
    return { kind: "unsafe" };
  }
  return {
    kind: "lookup",
    word,
    ...(anchor ? { anchor: decode(anchor) } : {}),
    ...(dictionaryIds?.length ? { dictionaryIds } : {}),
  };
}

export function classifyArticleLink(
  rawUrl: string,
  context: ResourceContext,
): ArticleLinkAction {
  const value = rawUrl.trim();
  if (!value || value === "#") {
    return { kind: "anchor", anchor: "" };
  }
  if (value.startsWith("#")) {
    return { kind: "anchor", anchor: decode(value.slice(1)) };
  }
  const lookup = parseLookupUrl(value);
  if (lookup) {
    return lookup;
  }
  const scheme = /^([a-z][a-z\d+.-]*):/i.exec(value)?.[1]?.toLowerCase();
  if (
    scheme === "javascript" ||
    scheme === "vbscript" ||
    scheme === "file" ||
    scheme === "data"
  ) {
    return { kind: "unsafe" };
  }
  if (scheme && UNSUPPORTED_INTERNAL_SCHEMES.has(scheme)) {
    return { kind: "unsafe" };
  }
  if (scheme && CUSTOM_RESOURCE_SCHEMES.has(scheme)) {
    const kind = scheme === "gdau" ? "audio" : scheme === "gdvideo" ? "video" : "resource";
    return { kind, url: resolveResourceUrl(value, context) };
  }
  if (
    value.startsWith("//") ||
    scheme === "http" ||
    scheme === "https" ||
    scheme === "mailto" ||
    scheme === "tel"
  ) {
    return { kind: "external", url: value };
  }
  if (scheme) {
    return { kind: "unsafe" };
  }
  if (value.startsWith("/")) {
    return { kind: "resource", url: resolveResourceUrl(value, context) };
  }
  const [word, anchor] = value.split("#", 2);
  if (!word) {
    return { kind: "anchor", anchor: decode(anchor ?? "") };
  }
  return {
    kind: "lookup",
    word: decode(word),
    ...(anchor ? { anchor: decode(anchor) } : {}),
  };
}
