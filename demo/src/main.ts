import {
  DictionaryClient,
  DARK_THEME_TOKENS,
  GOLDENDICT_EVENTS,
  LIGHT_THEME_TOKENS,
  resolveThemeMode,
  type DictionarySummary,
  type GoldenDictPreset,
  type GoldenDictTheme,
  type GoldenDictView,
  type ThemeMode,
  type ViewStateEventDetail,
} from "@goldendict-web/frontend";
import "./demo.css";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) {
    throw new Error(`Missing demo element #${id}`);
  }
  return found as T;
}

const apiBaseInput = element<HTMLInputElement>("api-base");
const dictionaryView = element<GoldenDictView>("dictionary-view");
const scriptPolicyInput = element<HTMLSelectElement>("script-policy");
const dictionaryList = element<HTMLDivElement>("dictionary-list");
const queryInput = element<HTMLInputElement>("query");
const statePill = element<HTMLSpanElement>("view-state");
const lookupTime = element<HTMLSpanElement>("lookup-time");
const connection = element<HTMLDivElement>("connection-text").parentElement as HTMLDivElement;
const connectionText = element<HTMLSpanElement>("connection-text");
const eventLog = element<HTMLOListElement>("event-log");
const toast = element<HTMLDivElement>("toast");
let client = new DictionaryClient({ baseUrl: apiBaseInput.value });
let dictionaries: DictionarySummary[] = [];
let toastTimer: ReturnType<typeof globalThis.setTimeout> | undefined;

const DEMO_PALETTES = {
  light: {
    accentColor: "#3459d6",
    linkColor: LIGHT_THEME_TOKENS.linkColor,
    backgroundColor: LIGHT_THEME_TOKENS.backgroundColor,
    headerColor: "#eaf0ff",
  },
  dark: {
    accentColor: DARK_THEME_TOKENS.accentColor,
    linkColor: DARK_THEME_TOKENS.linkColor,
    backgroundColor: DARK_THEME_TOKENS.backgroundColor,
    headerColor: DARK_THEME_TOKENS.headerColor,
  },
} as const;

function showToast(message: string): void {
  if (toastTimer !== undefined) {
    globalThis.clearTimeout(toastTimer);
  }
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = globalThis.setTimeout(() => {
    toast.hidden = true;
  }, 3500);
}

function logEvent(name: string, detail: unknown): void {
  const row = document.createElement("li");
  const safeDetail =
    detail instanceof Error
      ? detail.message
      : JSON.stringify(detail, (_key, value: unknown) =>
          value instanceof Error ? value.message : value,
        );
  row.textContent = `${new Date().toLocaleTimeString()} ${name} ${safeDetail ?? ""}`;
  eventLog.prepend(row);
  while (eventLog.children.length > 40) {
    eventLog.lastElementChild?.remove();
  }
}

function selectedDictionaryIds(): string[] {
  return [...dictionaryList.querySelectorAll<HTMLInputElement>("input:checked")].map(
    (input) => input.value,
  );
}

function renderDictionaries(): void {
  dictionaryList.replaceChildren();
  if (!dictionaries.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No dictionaries are loaded on the server.";
    dictionaryList.append(empty);
    return;
  }
  for (const dictionary of dictionaries) {
    const label = document.createElement("label");
    label.className = "dictionary-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = dictionary.id;
    checkbox.checked = true;
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = dictionary.name;
    const meta = document.createElement("small");
    meta.textContent = [dictionary.format, dictionary.sourceLanguage, dictionary.targetLanguage]
      .filter(Boolean)
      .join(" · ");
    copy.append(title, meta);
    label.append(checkbox, copy);
    dictionaryList.append(label);
  }
}

function useApiBase(): void {
  client = new DictionaryClient({ baseUrl: apiBaseInput.value });
  dictionaryView.client = client;
}

async function refreshDictionaries(): Promise<void> {
  useApiBase();
  connection.dataset.state = "connecting";
  connectionText.textContent = "Connecting…";
  dictionaryList.innerHTML = '<p class="hint">Loading dictionaries…</p>';
  try {
    dictionaries = await client.listDictionaries();
    renderDictionaries();
    connection.dataset.state = "online";
    connectionText.textContent = `${dictionaries.length} dictionar${dictionaries.length === 1 ? "y" : "ies"} ready`;
  } catch (error) {
    dictionaries = [];
    renderDictionaries();
    connection.dataset.state = "offline";
    connectionText.textContent = "API unavailable";
    showToast(error instanceof Error ? error.message : String(error));
  }
}

function currentTheme(): GoldenDictTheme {
  return {
    preset: element<HTMLSelectElement>("preset").value as GoldenDictPreset,
    mode: element<HTMLSelectElement>("theme-mode").value as ThemeMode,
    brandName: element<HTMLInputElement>("brand-name").value,
    logoUrl: element<HTMLInputElement>("logo-url").value || undefined,
    tokens: {
      accentColor: element<HTMLInputElement>("accent-color").value,
      selectionColor: element<HTMLInputElement>("accent-color").value,
      linkColor: element<HTMLInputElement>("link-color").value,
      backgroundColor: element<HTMLInputElement>("background-color").value,
      headerColor: element<HTMLInputElement>("header-color").value,
    },
    cssText: element<HTMLTextAreaElement>("custom-css").value,
  };
}

function applyTheme(): void {
  dictionaryView.theme = currentTheme();
}

function applyModePalette(mode: ThemeMode): void {
  const palette = DEMO_PALETTES[resolveThemeMode(mode)];
  element<HTMLInputElement>("accent-color").value = palette.accentColor;
  element<HTMLInputElement>("link-color").value = palette.linkColor;
  element<HTMLInputElement>("background-color").value = palette.backgroundColor;
  element<HTMLInputElement>("header-color").value = palette.headerColor;
  applyTheme();
}

document.getElementById("search-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  const word = queryInput.value.trim();
  if (!word) {
    queryInput.focus();
    return;
  }
  const selected = selectedDictionaryIds();
  dictionaryView.dictionaryIds = selected;
  void dictionaryView.lookup(word, selected);
});

document.getElementById("refresh")?.addEventListener("click", () => {
  void refreshDictionaries();
});
document.getElementById("select-all")?.addEventListener("click", () => {
  dictionaryList
    .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
    .forEach((checkbox) => {
      checkbox.checked = true;
    });
});
apiBaseInput.addEventListener("change", () => void refreshDictionaries());
scriptPolicyInput.addEventListener("change", () => {
  dictionaryView.scriptPolicy =
    scriptPolicyInput.value === "sandboxed" ? "sandboxed" : "none";
});

for (const id of [
  "preset",
  "brand-name",
  "logo-url",
  "accent-color",
  "link-color",
  "background-color",
  "header-color",
  "custom-css",
]) {
  document.getElementById(id)?.addEventListener("input", applyTheme);
  document.getElementById(id)?.addEventListener("change", applyTheme);
}

element<HTMLSelectElement>("theme-mode").addEventListener("change", (event) => {
  applyModePalette((event.currentTarget as HTMLSelectElement).value as ThemeMode);
});

globalThis.matchMedia?.("(prefers-color-scheme: dark)").addEventListener(
  "change",
  () => {
    const mode = element<HTMLSelectElement>("theme-mode").value as ThemeMode;
    if (mode === "auto") {
      applyModePalette(mode);
    }
  },
);

document.getElementById("reset-theme")?.addEventListener("click", () => {
  element<HTMLSelectElement>("preset").value = "default";
  element<HTMLSelectElement>("theme-mode").value = "light";
  element<HTMLInputElement>("brand-name").value = "Northstar Lexicon";
  element<HTMLInputElement>("logo-url").value = "";
  element<HTMLTextAreaElement>("custom-css").value = "";
  applyModePalette("light");
});

dictionaryView.addEventListener(GOLDENDICT_EVENTS.lookup, (event) => {
  const detail = (event as CustomEvent<{ word: string }>).detail;
  queryInput.value = detail.word;
  logEvent(GOLDENDICT_EVENTS.lookup, detail);
});
dictionaryView.addEventListener(GOLDENDICT_EVENTS.stateChange, (event) => {
  const detail = (event as CustomEvent<ViewStateEventDetail>).detail;
  statePill.textContent = detail.state.replace("-", " ");
  statePill.dataset.state = detail.state;
  if (detail.state === "ready" || detail.state === "not-found") {
    lookupTime.textContent = dictionaryView.response
      ? `${dictionaryView.response.articles.length} result(s) · ${dictionaryView.response.lookupTimeMs.toFixed(1)} ms`
      : "";
  }
  logEvent(GOLDENDICT_EVENTS.stateChange, detail);
});
for (const eventName of [
  GOLDENDICT_EVENTS.activeArticleChange,
  GOLDENDICT_EVENTS.articleToggle,
  GOLDENDICT_EVENTS.mediaRequest,
  GOLDENDICT_EVENTS.externalLink,
]) {
  dictionaryView.addEventListener(eventName, (event) => {
    logEvent(eventName, (event as CustomEvent<unknown>).detail);
  });
}

applyTheme();
void refreshDictionaries();
