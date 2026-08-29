import { rewriteBuiltinAssetUrls } from "../assets";
import type { GoldenDictPreset } from "../types";
import { GOLDENDICT_VENDOR_CSS } from "./vendor.generated";

const baseCss = GOLDENDICT_VENDOR_CSS["article-style.css"];
const printCss = GOLDENDICT_VENDOR_CSS["article-style-print.css"];
const babylonCss = GOLDENDICT_VENDOR_CSS["article-style-st-babylon.css"];
const classicCss = GOLDENDICT_VENDOR_CSS["article-style-st-classic.css"];
const lingoesBlueCss =
  GOLDENDICT_VENDOR_CSS["article-style-st-lingoes-blue.css"];
const lingoesCss = GOLDENDICT_VENDOR_CSS["article-style-st-lingoes.css"];
const lingvoCss = GOLDENDICT_VENDOR_CSS["article-style-st-lingvo.css"];
const modernCss = GOLDENDICT_VENDOR_CSS["article-style-st-modern.css"];

const presets: Readonly<Record<GoldenDictPreset, string>> = {
  default: "",
  classic: classicCss,
  modern: modernCss,
  lingvo: lingvoCss,
  babylon: babylonCss,
  lingoes: lingoesCss,
  "lingoes-blue": lingoesBlueCss,
};

export const GOLDENDICT_BASE_CSS = rewriteBuiltinAssetUrls(baseCss);
export const GOLDENDICT_PRINT_CSS = rewriteBuiltinAssetUrls(printCss);

export function getGoldenDictPresetCss(
  preset: GoldenDictPreset = "default",
): string {
  return rewriteBuiltinAssetUrls(presets[preset]);
}
