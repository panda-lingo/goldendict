import { describe, expect, it, vi } from "vitest";
import { DictionaryClient } from "../src/client/dictionary-client";
import {
  GoldenDictView,
  defineGoldendictView,
} from "../src/element/goldendict-view";

describe("GoldenDictView requests", () => {
  it("sizes itself from its container and keeps narrow chrome wrap-safe", () => {
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    const styles = view.shadowRoot?.querySelector("style")?.textContent ?? "";

    expect(view.scriptPolicy).toBe("none");
    expect(view.layoutMode).toBe("responsive");
    expect(styles).toContain("width:100%");
    expect(styles).toContain("max-width:100%");
    expect(styles).toContain("container:goldendict-view / inline-size");
    expect(styles).toContain("@container goldendict-view (max-width:30rem)");
    expect(styles).toContain("overflow-wrap:anywhere");
  });

  it("rerenders an article when its layout policy changes", async () => {
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    view.setLookupResponse({
      word: "layout",
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict",
          html: "<p>Article</p>",
        },
      ],
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    expect(view.shadowRoot?.querySelector("iframe")?.srcdoc).toContain(
      'data-gd-style="responsive"',
    );

    view.layoutMode = "fidelity";
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const html = view.shadowRoot?.querySelector("iframe")?.srcdoc ?? "";
    expect(html).toContain('data-gd-layout="fidelity"');
    expect(html).not.toContain('data-gd-style="responsive"');
  });

  it("aborts an in-flight lookup when a newer lookup starts", async () => {
    let firstSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/lookup/first")) {
        firstSignal = init?.signal as AbortSignal;
        return new Promise<Response>((_resolve, reject) => {
          firstSignal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            word: "second",
            articles: [],
            suggestions: [],
            lookupTimeMs: 1,
          }),
          { status: 200 },
        ),
      );
    });
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    view.client = new DictionaryClient({ fetch: fetchMock });
    document.body.append(view);

    const first = view.lookup("first");
    const second = view.lookup("second");
    await Promise.all([first, second]);
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

    expect(firstSignal?.aborted).toBe(true);
    expect(view.response?.word).toBe("second");
    expect(view.shadowRoot?.querySelector("iframe")?.getAttribute("srcdoc")).toContain(
      "second",
    );
    view.remove();
  });

  it("uses a fresh measurable iframe for each scripted dictionary result", async () => {
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    const initialFrame = view.shadowRoot?.querySelector("iframe");
    expect(initialFrame).not.toBeNull();

    view.setLookupResponse({
      word: "cached",
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict",
          html: '<script src="dictionary.js"></script><p>Cached article</p>',
        },
      ],
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const firstResultFrame = view.shadowRoot?.querySelector("iframe");
    expect(firstResultFrame).not.toBe(initialFrame);
    expect(firstResultFrame?.hidden).toBe(false);
    expect(firstResultFrame?.srcdoc).toContain("Cached article");

    view.setLookupResponse({
      word: "next",
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict",
          html: "<p>Next article</p>",
        },
      ],
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const secondResultFrame = view.shadowRoot?.querySelector("iframe");
    expect(secondResultFrame).not.toBe(firstResultFrame);
    expect(secondResultFrame?.hidden).toBe(false);
    expect(secondResultFrame?.srcdoc).toContain("Next article");
  });

  it("isolates bridge messages between consecutive article documents", async () => {
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    document.body.append(view);

    const response = (word: string) => ({
      word,
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict" as const,
          html: `<p>${word}</p>`,
        },
      ],
    });
    const bridgeId = (frame: HTMLIFrameElement): string => {
      const match = frame.srcdoc.match(/"instanceId":"([^"]+)"/);
      expect(match).not.toBeNull();
      return match?.[1] ?? "";
    };

    view.setLookupResponse(response("first"));
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const firstFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    const firstBridgeId = bridgeId(firstFrame);

    view.setLookupResponse(response("second"));
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const secondFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    const secondBridgeId = bridgeId(secondFrame);

    expect(secondFrame).not.toBe(firstFrame);
    expect(secondBridgeId).not.toBe(firstBridgeId);
    expect(secondFrame.style.height).toBe("8rem");

    globalThis.dispatchEvent(
      new MessageEvent("message", {
        source: secondFrame.contentWindow,
        data: {
          namespace: "goldendict-web",
          instanceId: firstBridgeId,
          type: "height",
          detail: { height: 999 },
        },
      }),
    );
    expect(secondFrame.style.height).toBe("8rem");

    globalThis.dispatchEvent(
      new MessageEvent("message", {
        source: secondFrame.contentWindow,
        data: {
          namespace: "goldendict-web",
          instanceId: secondBridgeId,
          type: "height",
          detail: { height: 321 },
        },
      }),
    );
    expect(secondFrame.style.height).toBe("321px");
    expect(view.state).toBe("ready");
    view.remove();
  });

  it("discards sandbox documents when aborted, errored, or cleared", async () => {
    defineGoldendictView();
    const view = document.createElement("goldendict-view") as GoldenDictView;
    view.scriptPolicy = "sandboxed";

    view.setLookupResponse({
      word: "scripted",
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict",
          html: '<script src="dictionary.js"></script><p>Article</p>',
        },
      ],
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const renderedFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    expect(renderedFrame.srcdoc).toContain("dictionary.js");

    view.abort();
    const abortedFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    expect(abortedFrame).not.toBe(renderedFrame);
    expect(abortedFrame.hidden).toBe(true);
    expect(abortedFrame.hasAttribute("srcdoc")).toBe(false);

    view.setLookupResponse({
      word: "before-error",
      lookupTimeMs: 1,
      suggestions: [],
      articles: [
        {
          dictionaryId: "fixture",
          dictionaryName: "Fixture",
          format: "mdict",
          html: '<script src="dictionary.js"></script><p>Before error</p>',
        },
      ],
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const beforeErrorFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    view.client = new DictionaryClient({
      fetch: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: "Unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    });

    await view.lookup("failed");
    const errorFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    expect(errorFrame).not.toBe(beforeErrorFrame);
    expect(errorFrame.hidden).toBe(true);
    expect(errorFrame.hasAttribute("srcdoc")).toBe(false);
    expect(view.state).toBe("error");

    view.clear();
    const clearedFrame = view.shadowRoot?.querySelector(
      "iframe",
    ) as HTMLIFrameElement;
    expect(clearedFrame).not.toBe(errorFrame);
    expect(clearedFrame.hidden).toBe(true);
    expect(clearedFrame.hasAttribute("srcdoc")).toBe(false);
    expect(view.state).toBe("idle");
  });
});
