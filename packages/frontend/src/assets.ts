import arrowSvg from "./assets/icons/arrow.svg?raw";
import audioPng from "./assets/icons/audio.png?url";
import collapseArticleHoveredSvg from "./assets/icons/collapse_article_hovered.svg?raw";
import collapseArticleSvg from "./assets/icons/collapse_article.svg?raw";
import collapseOptSvg from "./assets/icons/collapse_opt.svg?raw";
import documentPng from "./assets/icons/document.png?url";
import downArrowSvg from "./assets/icons/downarrow.svg?raw";
import expandArticleHoveredSvg from "./assets/icons/expand_article_hovered.svg?raw";
import expandArticleSvg from "./assets/icons/expand_article.svg?raw";
import expandOptSvg from "./assets/icons/expand_opt.svg?raw";
import oldArrowSvg from "./assets/icons/old-arrow.svg?raw";
import oldDownArrowSvg from "./assets/icons/old-downarrow.svg?raw";
import playSoundSvg from "./assets/icons/playsound.svg?raw";
import videoSvg from "./assets/icons/video.svg?raw";
import warningSvg from "./assets/icons/warning.svg?raw";

function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export const BUILTIN_ASSET_URLS: Readonly<Record<string, string>> = {
  "arrow.svg": svgDataUrl(arrowSvg),
  "audio.png": audioPng,
  "collapse_article.svg": svgDataUrl(collapseArticleSvg),
  "collapse_article_hovered.svg": svgDataUrl(collapseArticleHoveredSvg),
  "collapse_opt.svg": svgDataUrl(collapseOptSvg),
  "document.png": documentPng,
  "downarrow.svg": svgDataUrl(downArrowSvg),
  "expand_article.svg": svgDataUrl(expandArticleSvg),
  "expand_article_hovered.svg": svgDataUrl(expandArticleHoveredSvg),
  "expand_opt.svg": svgDataUrl(expandOptSvg),
  "old-arrow.svg": svgDataUrl(oldArrowSvg),
  "old-downarrow.svg": svgDataUrl(oldDownArrowSvg),
  "playsound.svg": svgDataUrl(playSoundSvg),
  "video.svg": svgDataUrl(videoSvg),
  "warning.svg": svgDataUrl(warningSvg),
};

export function resolveBuiltinAsset(url: string): string | undefined {
  const match = /^qrc:\/{2,3}(?:icons\/)?([^?#]+)(?:[?#].*)?$/i.exec(url);
  return match?.[1] ? BUILTIN_ASSET_URLS[match[1]] : undefined;
}

export function rewriteBuiltinAssetUrls(css: string): string {
  return css.replace(
    /qrc:\/{2,3}icons\/([a-z0-9_.-]+)/gi,
    (original, fileName: string) => BUILTIN_ASSET_URLS[fileName] ?? original,
  );
}
