import { describe, expect, it, vi } from "vitest";
import { DictionaryClient } from "../src/client/dictionary-client";
import {
  GoldenDictView,
  defineGoldendictView,
} from "../src/element/goldendict-view";

describe("GoldenDictView requests", () => {
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

    expect(firstSignal?.aborted).toBe(true);
    expect(view.response?.word).toBe("second");
    expect(view.shadowRoot?.querySelector("iframe")?.getAttribute("srcdoc")).toContain(
      "second",
    );
    view.remove();
  });
});
