import { DictionaryClient } from "../client/dictionary-client";
import { buildArticleDocument } from "../renderer/article-document";
import type {
  ActiveArticleEventDetail,
  ArticleLayoutMode,
  ArticleToggleEventDetail,
  DictionaryClientOptions,
  ExternalLinkEventDetail,
  GoldenDictTheme,
  LookupEventDetail,
  LookupResponse,
  MediaRequestEventDetail,
  ScriptPolicy,
  ViewState,
  ViewStateEventDetail,
} from "../types";
import { GOLDENDICT_EVENTS } from "../types";

const SHADOW_STYLES = `
  :host{display:block;box-sizing:border-box;width:100%;min-width:0;max-width:100%;color:#222;font-family:system-ui,sans-serif;container:goldendict-view / inline-size}
  .shell{position:relative;box-sizing:border-box;width:100%;min-width:0;max-width:100%;min-height:8rem;border-radius:var(--gd-host-radius,8px);overflow:hidden;background:var(--gd-host-background,#fff)}
  .brand{display:flex;align-items:center;gap:.65rem;min-width:0;padding:.65rem .9rem;border-bottom:1px solid var(--gd-host-border,#e3e3e3);background:var(--gd-host-surface,#f7f9fb);font-weight:650}
  .brand[hidden]{display:none}
  .brand img{display:block;flex:0 0 auto;width:1.75rem;height:1.75rem;object-fit:contain}
  .brand img[hidden]{display:none}
  .brand span{min-width:0;overflow-wrap:anywhere}
  .status{display:grid;place-items:center;min-height:8rem;padding:1.25rem;text-align:center;color:var(--gd-host-muted,#59636e)}
  .status[hidden]{display:none}
  .status[data-state="error"]{color:var(--gd-host-error,#a21d2d)}
  .spinner{width:1.25rem;height:1.25rem;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .75s linear infinite;margin:0 auto .7rem}
  iframe{display:block;box-sizing:border-box;width:100%;min-width:0;max-width:100%;min-height:8rem;border:0;background:transparent}
  iframe[hidden]{display:none}
  @keyframes spin{to{transform:rotate(360deg)}}
  @container goldendict-view (max-width:30rem){.brand{gap:.5rem;padding:.55rem .65rem}.status{padding:1rem .75rem}}
  @media (prefers-reduced-motion:reduce){.spinner{animation:none}}
`;

interface BridgeMessage {
  namespace?: string;
  instanceId?: string;
  type?: string;
  detail?: unknown;
}

function makeInstanceId(): string {
  return globalThis.crypto?.randomUUID?.() ??
    `gd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

export class GoldenDictView extends HTMLElement {
  static readonly observedAttributes = [
    "api-base",
    "word",
    "preset",
    "theme-mode",
    "script-policy",
    "layout-mode",
  ];

  readonly instanceId = makeInstanceId();
  private frame: HTMLIFrameElement;
  private readonly statusElement: HTMLDivElement;
  private readonly brandElement: HTMLDivElement;
  private readonly brandImage: HTMLImageElement;
  private readonly brandText: HTMLSpanElement;
  private clientValue: DictionaryClient;
  private requestController?: AbortController;
  private requestSequence = 0;
  private renderSequence = 0;
  private activeBridgeInstanceId?: string;
  private responseValue?: LookupResponse;
  private themeValue: GoldenDictTheme = {};
  private stateValue: ViewState = "idle";
  private dictionaryIdsValue: string[] = [];
  private pendingAnchor?: string;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    shadow.innerHTML = `<style>${SHADOW_STYLES}</style>
      <section class="shell" part="container">
        <div class="brand" part="brand" hidden>
          <img alt="" hidden><span></span>
        </div>
        <div class="status" part="status" role="status" aria-live="polite"></div>
        <iframe part="article" title="Dictionary article" sandbox="allow-scripts"
          referrerpolicy="no-referrer" hidden></iframe>
      </section>`;
    this.frame = shadow.querySelector("iframe") as HTMLIFrameElement;
    this.statusElement = shadow.querySelector(".status") as HTMLDivElement;
    this.brandElement = shadow.querySelector(".brand") as HTMLDivElement;
    this.brandImage = this.brandElement.querySelector("img") as HTMLImageElement;
    this.brandText = this.brandElement.querySelector("span") as HTMLSpanElement;
    this.clientValue = new DictionaryClient({ baseUrl: this.apiBase });
    this.updateBrand();
    this.setState("idle");
  }

  connectedCallback(): void {
    globalThis.addEventListener("message", this.handleBridgeMessage);
    const attributeWord = this.getAttribute("word")?.trim();
    if (attributeWord) {
      void this.lookup(attributeWord);
    }
  }

  disconnectedCallback(): void {
    globalThis.removeEventListener("message", this.handleBridgeMessage);
    this.abort();
  }

  attributeChangedCallback(
    name: string,
    oldValue: string | null,
    newValue: string | null,
  ): void {
    if (oldValue === newValue) {
      return;
    }
    if (name === "api-base") {
      this.clientValue = new DictionaryClient({ baseUrl: newValue ?? "/api/v1" });
    } else if (name === "word" && this.isConnected && newValue?.trim()) {
      void this.lookup(newValue);
    } else if (name === "preset") {
      this.theme = {
        ...this.themeValue,
        preset: (newValue || "default") as GoldenDictTheme["preset"],
      };
    } else if (name === "theme-mode") {
      this.theme = {
        ...this.themeValue,
        mode: (newValue || "light") as GoldenDictTheme["mode"],
      };
    } else if (
      (name === "script-policy" || name === "layout-mode") &&
      this.responseValue
    ) {
      this.renderResponse(this.responseValue);
    }
  }

  get apiBase(): string {
    return this.getAttribute("api-base")?.trim() || "/api/v1";
  }

  set apiBase(value: string) {
    this.setAttribute("api-base", value);
  }

  get client(): DictionaryClient {
    return this.clientValue;
  }

  set client(value: DictionaryClient) {
    this.clientValue = value;
  }

  get theme(): GoldenDictTheme {
    return this.themeValue;
  }

  set theme(value: GoldenDictTheme) {
    this.themeValue = { ...value, tokens: { ...value.tokens } };
    this.updateBrand();
    if (this.responseValue) {
      this.renderResponse(this.responseValue);
    }
  }

  get scriptPolicy(): ScriptPolicy {
    return this.getAttribute("script-policy") === "sandboxed"
      ? "sandboxed"
      : "none";
  }

  set scriptPolicy(value: ScriptPolicy) {
    this.setAttribute("script-policy", value);
  }

  get layoutMode(): ArticleLayoutMode {
    return this.getAttribute("layout-mode") === "fidelity"
      ? "fidelity"
      : "responsive";
  }

  set layoutMode(value: ArticleLayoutMode) {
    this.setAttribute("layout-mode", value);
  }

  get dictionaryIds(): readonly string[] {
    return this.dictionaryIdsValue;
  }

  set dictionaryIds(value: readonly string[]) {
    this.dictionaryIdsValue = [...value];
  }

  get state(): ViewState {
    return this.stateValue;
  }

  get response(): LookupResponse | undefined {
    return this.responseValue;
  }

  configureClient(options: DictionaryClientOptions): void {
    this.clientValue = new DictionaryClient(options);
  }

  async lookup(
    word: string,
    dictionaryIds: readonly string[] = this.dictionaryIdsValue,
  ): Promise<void> {
    const normalizedWord = word.trim();
    if (!normalizedWord) {
      this.clear();
      return;
    }
    this.abort();
    const sequence = ++this.requestSequence;
    const controller = new AbortController();
    this.requestController = controller;
    this.dictionaryIdsValue = [...dictionaryIds];
    this.setState("loading", { word: normalizedWord });
    try {
      const response = await this.clientValue.lookup(normalizedWord, {
        dictionaryIds,
        signal: controller.signal,
      });
      if (sequence !== this.requestSequence || controller.signal.aborted) {
        return;
      }
      this.setLookupResponse(response);
    } catch (error) {
      if (sequence !== this.requestSequence || isAbortError(error)) {
        return;
      }
      const normalizedError =
        error instanceof Error ? error : new Error(String(error));
      this.responseValue = undefined;
      this.resetFrame();
      this.setState("error", { word: normalizedWord, error: normalizedError });
    } finally {
      if (sequence === this.requestSequence) {
        this.requestController = undefined;
      }
    }
  }

  setLookupResponse(response: LookupResponse): void {
    this.responseValue = response;
    this.renderResponse(response);
  }

  abort(): void {
    this.requestController?.abort();
    this.requestController = undefined;
    this.renderSequence += 1;
    this.resetFrame();
  }

  clear(): void {
    this.abort();
    this.requestSequence += 1;
    this.responseValue = undefined;
    this.setState("idle");
  }

  scrollToArticle(dictionaryId: string): void {
    this.postCommand({ type: "scroll-article", dictionaryId });
  }

  private renderResponse(response: LookupResponse): void {
    const renderSequence = ++this.renderSequence;
    const bridgeInstanceId = `${this.instanceId}-${renderSequence}`;
    this.activeBridgeInstanceId = bridgeInstanceId;
    const frame = this.replaceFrame(false);
    frame.title = response.word
      ? `Dictionary results for ${response.word}`
      : "Dictionary article";
    const srcdoc = buildArticleDocument(response, {
      apiBaseUrl: this.clientValue.baseUrl,
      instanceId: bridgeInstanceId,
      scriptPolicy: this.scriptPolicy,
      layoutMode: this.layoutMode,
      theme: this.themeValue,
    });
    requestAnimationFrame(() => {
      if (renderSequence !== this.renderSequence || frame !== this.frame) {
        return;
      }
      frame.srcdoc = srcdoc;
      this.statusElement.hidden = true;
    });
  }

  private resetFrame(): void {
    this.activeBridgeInstanceId = undefined;
    this.replaceFrame(true);
  }

  private replaceFrame(hidden: boolean): HTMLIFrameElement {
    const previous = this.frame;
    const frame = this.ownerDocument.createElement("iframe");
    frame.setAttribute("part", "article");
    frame.title = "Dictionary article";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.referrerPolicy = "no-referrer";
    frame.style.height = "8rem";
    frame.hidden = hidden;
    frame.addEventListener("load", () => {
      if (this.frame === frame && frame.hasAttribute("srcdoc")) {
        this.handleFrameLoaded();
      }
    });
    previous.replaceWith(frame);
    this.frame = frame;
    // Cached dictionary CSS/JS can execute immediately during navigation.
    // Establish a measurable, fresh browsing context before assigning srcdoc.
    void frame.offsetWidth;
    return frame;
  }

  private handleFrameLoaded(): void {
    if (!this.responseValue) {
      return;
    }
    this.setState(
      this.responseValue.articles.length ? "ready" : "not-found",
      { word: this.responseValue.word },
    );
    if (this.pendingAnchor) {
      this.postCommand({ type: "scroll-anchor", anchor: this.pendingAnchor });
      this.pendingAnchor = undefined;
    }
  }

  private readonly handleBridgeMessage = (event: MessageEvent): void => {
    if (event.source !== this.frame.contentWindow) {
      return;
    }
    const message = event.data as BridgeMessage;
    if (
      message.namespace !== "goldendict-web" ||
      message.instanceId !== this.activeBridgeInstanceId ||
      !message.type
    ) {
      return;
    }
    const detail = (message.detail ?? {}) as Record<string, unknown>;
    switch (message.type) {
      case "ready":
        this.handleFrameLoaded();
        break;
      case "height": {
        const height = Number(detail.height);
        if (Number.isFinite(height) && height > 0) {
          this.frame.style.height = `${Math.min(Math.max(height, 128), 100_000)}px`;
          // A valid measurement proves that the current bridge is initialized.
          // Do not keep the host in loading state while slow images or fonts
          // delay the iframe's window load event.
          this.handleFrameLoaded();
        }
        break;
      }
      case "lookup":
        this.handleLookupMessage(detail);
        break;
      case "active-article":
        this.emit<ActiveArticleEventDetail>(GOLDENDICT_EVENTS.activeArticleChange, {
          dictionaryId: String(detail.dictionaryId ?? ""),
        });
        break;
      case "article-toggle":
        this.emit<ArticleToggleEventDetail>(GOLDENDICT_EVENTS.articleToggle, {
          dictionaryId: String(detail.dictionaryId ?? ""),
          collapsed: Boolean(detail.collapsed),
        });
        break;
      case "media":
        this.handleMediaMessage(detail);
        break;
      case "external-link":
        this.handleExternalLink(String(detail.url ?? ""));
        break;
    }
  };

  private handleLookupMessage(detail: Record<string, unknown>): void {
    const word = String(detail.word ?? "").trim();
    if (!word) {
      return;
    }
    const dictionaries = Array.isArray(detail.dictionaryIds)
      ? detail.dictionaryIds.map(String)
      : this.dictionaryIdsValue;
    const eventDetail: LookupEventDetail = {
      word,
      ...(detail.anchor ? { anchor: String(detail.anchor) } : {}),
      ...(dictionaries.length ? { dictionaryIds: [...dictionaries] } : {}),
    };
    const event = this.emit(GOLDENDICT_EVENTS.lookup, eventDetail, true);
    if (!event.defaultPrevented) {
      this.pendingAnchor = eventDetail.anchor;
      void this.lookup(word, dictionaries);
    }
  }

  private handleMediaMessage(detail: Record<string, unknown>): void {
    const kind =
      detail.kind === "video" || detail.kind === "resource"
        ? detail.kind
        : "audio";
    const eventDetail: MediaRequestEventDetail = {
      kind,
      url: String(detail.url ?? ""),
      ...(detail.dictionaryId
        ? { dictionaryId: String(detail.dictionaryId) }
        : {}),
    };
    if (!eventDetail.url) {
      return;
    }
    const event = this.emit(GOLDENDICT_EVENTS.mediaRequest, eventDetail, true);
    if (event.defaultPrevented) {
      return;
    }
    if (kind === "audio") {
      void new Audio(eventDetail.url).play().catch(() => undefined);
    } else {
      this.openExternal(eventDetail.url);
    }
  }

  private handleExternalLink(url: string): void {
    if (!url) {
      return;
    }
    const event = this.emit<ExternalLinkEventDetail>(
      GOLDENDICT_EVENTS.externalLink,
      { url },
      true,
    );
    if (!event.defaultPrevented) {
      this.openExternal(url);
    }
  }

  private openExternal(url: string): void {
    const opened = globalThis.open?.(url, "_blank", "noopener,noreferrer");
    if (opened) {
      opened.opener = null;
    }
  }

  private updateBrand(): void {
    const brandName = this.themeValue.brandName?.trim() ?? "";
    const logoUrl = this.themeValue.logoUrl?.trim() ?? "";
    this.brandElement.hidden = !brandName && !logoUrl;
    this.brandText.textContent = brandName;
    this.brandImage.hidden = !logoUrl;
    if (logoUrl) {
      this.brandImage.src = logoUrl;
    } else {
      this.brandImage.removeAttribute("src");
    }
  }

  private setState(
    state: ViewState,
    context: { word?: string; error?: Error } = {},
  ): void {
    const changed = state !== this.stateValue;
    this.stateValue = state;
    this.statusElement.dataset.state = state;
    this.statusElement.hidden = state === "ready" || state === "not-found";
    if (state === "loading") {
      this.frame.hidden = true;
      this.statusElement.innerHTML = `<div><div class="spinner" aria-hidden="true"></div>Looking up <strong></strong>…</div>`;
      const strong = this.statusElement.querySelector("strong");
      if (strong) {
        strong.textContent = context.word ?? "";
      }
    } else if (state === "error") {
      this.statusElement.textContent =
        context.error?.message ?? "The dictionary request failed.";
    } else if (state === "idle") {
      this.statusElement.textContent = "Enter a word to search the loaded dictionaries.";
    } else {
      this.statusElement.textContent =
        state === "not-found" ? `No translation found for ${context.word ?? ""}.` : "";
    }
    if (changed) {
      this.emit<ViewStateEventDetail>(GOLDENDICT_EVENTS.stateChange, {
        state,
        ...(context.word ? { word: context.word } : {}),
        ...(context.error ? { error: context.error } : {}),
      });
    }
  }

  private postCommand(message: Record<string, unknown>): void {
    if (!this.activeBridgeInstanceId) {
      return;
    }
    this.frame.contentWindow?.postMessage(
      {
        namespace: "goldendict-web",
        instanceId: this.activeBridgeInstanceId,
        ...message,
      },
      "*",
    );
  }

  private emit<T>(
    name: string,
    detail: T,
    cancelable = false,
  ): CustomEvent<T> {
    const event = new CustomEvent<T>(name, {
      detail,
      bubbles: true,
      composed: true,
      cancelable,
    });
    this.dispatchEvent(event);
    return event;
  }
}

export function defineGoldendictView(
  tagName = "goldendict-view",
): typeof GoldenDictView {
  if (!globalThis.customElements) {
    return GoldenDictView;
  }
  const existing = globalThis.customElements.get(tagName);
  if (!existing) {
    globalThis.customElements.define(tagName, GoldenDictView);
    return GoldenDictView;
  }
  return existing as typeof GoldenDictView;
}

declare global {
  interface HTMLElementTagNameMap {
    "goldendict-view": GoldenDictView;
  }
}
