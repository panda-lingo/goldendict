import type { LookupArticle, ScriptPolicy } from "../types";
import {
  classifyArticleLink,
  resolveResourceUrl,
  type ArticleLinkAction,
  type ResourceContext,
} from "./link-router";

const RESOURCE_ATTRIBUTES = ["src", "poster", "data"] as const;

function isDirectBrowserUrl(url: string): boolean {
  return /^(?:data:|blob:|https?:|#)/i.test(url);
}

function declaredLinkAction(
  element: Element,
  href: string,
  context: ResourceContext,
): ArticleLinkAction | undefined {
  const declarations = [
    ["data-gd-audio", "audio"],
    ["data-gd-video", "video"],
    ["data-gd-resource", "resource"],
  ] as const;
  for (const [attribute, kind] of declarations) {
    if (element.hasAttribute(attribute)) {
      const declaredUrl = element.getAttribute(attribute)?.trim();
      return {
        kind,
        url: resolveResourceUrl(declaredUrl || href, context),
      };
    }
  }
  const declaredKind = element.getAttribute("data-gd-action")?.trim().toLowerCase();
  if (
    declaredKind === "audio" ||
    declaredKind === "video" ||
    declaredKind === "resource"
  ) {
    return { kind: declaredKind, url: resolveResourceUrl(href, context) };
  }
  if (element.hasAttribute("data-gd-lookup") || declaredKind === "lookup") {
    const declaredWord = element.getAttribute("data-gd-lookup")?.trim();
    if (declaredWord && declaredWord !== "true" && declaredWord !== "1") {
      return { kind: "lookup", word: declaredWord };
    }
    const classified = classifyArticleLink(href, context);
    if (classified.kind === "lookup") {
      return classified;
    }
    const word = element.getAttribute("data-gd-word")?.trim();
    return word ? { kind: "lookup", word } : { kind: "unsafe" };
  }
  if (declaredKind === "unsafe") {
    return { kind: "unsafe" };
  }
  return undefined;
}

function setActionAttributes(
  element: Element,
  action: ArticleLinkAction,
  dictionaryId: string,
): void {
  switch (action.kind) {
    case "anchor":
      element.setAttribute(
        "href",
        action.anchor ? `#${encodeURIComponent(action.anchor)}` : "#",
      );
      break;
    case "lookup":
      element.setAttribute("href", "#");
      element.setAttribute("data-gd-action", "lookup");
      element.setAttribute("data-gd-word", action.word);
      if (action.anchor) {
        element.setAttribute("data-gd-anchor", action.anchor);
      }
      if (action.dictionaryIds?.length) {
        element.setAttribute(
          "data-gd-dictionaries",
          action.dictionaryIds.join(","),
        );
      }
      break;
    case "audio":
    case "video":
    case "resource":
      element.setAttribute("href", action.url);
      element.setAttribute("data-gd-action", action.kind);
      element.setAttribute("data-gd-dictionary", dictionaryId);
      break;
    case "external":
      element.setAttribute("href", action.url);
      element.setAttribute("data-gd-action", "external");
      break;
    case "unsafe":
      element.setAttribute("href", "#");
      element.setAttribute("data-gd-action", "unsafe");
      break;
  }
}

export function rewriteCssResourceUrls(
  css: string,
  context: ResourceContext,
): string {
  const rewrittenUrls = css.replace(
    /url\(\s*(["']?)([^"')]+)\1\s*\)/gi,
    (match, quote: string, rawUrl: string) => {
      const value = rawUrl.trim();
      if (isDirectBrowserUrl(value)) {
        return match;
      }
      return `url(${quote}${resolveResourceUrl(value, context)}${quote})`;
    },
  );
  return rewrittenUrls.replace(
    /@import\s+(["'])([^"']+)\1/gi,
    (match, quote: string, rawUrl: string) => {
      if (isDirectBrowserUrl(rawUrl)) {
        return match;
      }
      return `@import ${quote}${resolveResourceUrl(rawUrl, context)}${quote}`;
    },
  );
}

function rewriteSrcset(value: string, context: ResourceContext): string {
  return value
    .split(/,\s+(?=[^,]+(?:\s+\d+(?:\.\d+)?[wx])?(?:,|$))/)
    .map((candidate) => {
      const match = /^(\S+)([\s\S]*)$/.exec(candidate.trim());
      if (!match?.[1] || isDirectBrowserUrl(match[1])) {
        return candidate.trim();
      }
      return `${resolveResourceUrl(match[1], context)}${match[2] ?? ""}`;
    })
    .join(", ");
}

function preserveOptionalPartTarget(element: Element): void {
  if (!element.classList.contains("hidden_expand_opt")) {
    return;
  }
  const handler = element.getAttribute("onclick") ?? "";
  const match = /gdExpandOptPart\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)/.exec(
    handler,
  );
  if (match?.[1] && match[2]) {
    element.setAttribute("data-gd-expander", match[1]);
    element.setAttribute("data-gd-optional", match[2]);
  }
}

export function prepareArticleHtml(
  article: LookupArticle,
  apiBaseUrl: string,
  scriptPolicy: ScriptPolicy,
): string {
  if (typeof document === "undefined") {
    throw new Error("Article rendering requires a browser document");
  }
  const context: ResourceContext = {
    apiBaseUrl,
    dictionaryId: article.dictionaryId,
    ...(article.iconUrl ? { iconUrl: article.iconUrl } : {}),
    ...(article.resourceBaseUrl
      ? { resourceBaseUrl: article.resourceBaseUrl }
      : {}),
  };
  const parsed = document.implementation.createHTMLDocument("");
  const container = parsed.createElement("div");
  container.innerHTML = article.html;

  container.querySelectorAll("base, meta[http-equiv='refresh' i]").forEach((node) => {
    node.remove();
  });
  if (scriptPolicy === "none") {
    container.querySelectorAll("script").forEach((node) => node.remove());
  }

  for (const element of container.querySelectorAll("*")) {
    preserveOptionalPartTarget(element);
    if (scriptPolicy === "none") {
      for (const attribute of [...element.attributes]) {
        if (/^on/i.test(attribute.name) || attribute.name.toLowerCase() === "srcdoc") {
          element.removeAttribute(attribute.name);
        }
      }
    }

    if (element instanceof HTMLAnchorElement || element.tagName === "AREA") {
      const href = element.getAttribute("href");
      if (href !== null) {
        setActionAttributes(
          element,
          declaredLinkAction(element, href, context) ??
            classifyArticleLink(href, context),
          article.dictionaryId,
        );
      }
    } else if (element.hasAttribute("href")) {
      const href = element.getAttribute("href") ?? "";
      if (!isDirectBrowserUrl(href)) {
        element.setAttribute("href", resolveResourceUrl(href, context));
      }
    }

    for (const attribute of RESOURCE_ATTRIBUTES) {
      const value = element.getAttribute(attribute);
      if (value === null || isDirectBrowserUrl(value)) {
        continue;
      }
      if (/^(?:javascript|vbscript|file):/i.test(value)) {
        element.removeAttribute(attribute);
      } else {
        element.setAttribute(attribute, resolveResourceUrl(value, context));
      }
    }
    const srcset = element.getAttribute("srcset");
    if (srcset) {
      element.setAttribute("srcset", rewriteSrcset(srcset, context));
    }
    const inlineStyle = element.getAttribute("style");
    if (inlineStyle) {
      element.setAttribute(
        "style",
        rewriteCssResourceUrls(inlineStyle, context),
      );
    }
  }

  for (const style of container.querySelectorAll("style")) {
    style.textContent = rewriteCssResourceUrls(style.textContent ?? "", context);
  }
  return container.innerHTML;
}
