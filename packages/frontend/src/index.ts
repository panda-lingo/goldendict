export { DictionaryApiError, DictionaryClient } from "./client/dictionary-client";
export {
  GoldenDictView,
  defineGoldendictView,
} from "./element/goldendict-view";
export {
  GOLDENDICT_SCHEME_SUPPORT,
  classifyArticleLink,
  resolveResourceUrl,
  type ArticleLinkAction,
  type ResourceContext,
} from "./renderer/link-router";
export {
  DARK_THEME_TOKENS,
  LIGHT_THEME_TOKENS,
  escapeStyleText,
  resolveThemeMode,
  themeToCss,
} from "./renderer/theme";
export { GOLDENDICT_EVENTS } from "./types";
export type * from "./types";

import { defineGoldendictView } from "./element/goldendict-view";

defineGoldendictView();
