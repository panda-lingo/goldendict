import { describe, expect, it, vi } from "vitest";
import { DictionaryClient } from "../src/client/dictionary-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("DictionaryClient", () => {
  it("normalizes dictionary envelopes and aliases", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        dictionaries: [
          {
            dictionaryId: "dict-1",
            dictionaryName: "Example",
            format: "stardict",
          },
        ],
      }),
    );
    const client = new DictionaryClient({
      baseUrl: "/api/v1/",
      fetch: fetchMock,
    });

    await expect(client.listDictionaries()).resolves.toEqual([
      { id: "dict-1", name: "Example", format: "stardict" },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/dictionaries",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("uses the encoded path lookup contract and comma-separated dictionary ids", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        word: "ice cream/冰淇淋",
        articles: [],
        suggestions: [],
        lookupTimeMs: 2.5,
      }),
    );
    const client = new DictionaryClient({ fetch: fetchMock });

    await client.lookup("ice cream/冰淇淋", {
      dictionaryIds: ["one", "two"],
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/lookup/ice%20cream%2F%E5%86%B0%E6%B7%87%E6%B7%8B?dictionary_ids=one%2Ctwo",
    );
  });

  it("passes catalog language filters and preserves the AbortSignal call form", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse([])),
    );
    const client = new DictionaryClient({ fetch: fetchMock });

    await client.listDictionaries({
      language: " en ",
      sourceLanguage: "en-US",
      targetLanguage: "fr",
    });
    const controller = new AbortController();
    await client.listDictionaries(controller.signal);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/dictionaries?language=en&source_language=en-US&target_language=fr",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/dictionaries");
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("rejects a blank catalog language filter", async () => {
    const client = new DictionaryClient({ fetch: vi.fn() });

    await expect(
      client.listDictionaries({ language: "  " }),
    ).rejects.toThrow("Dictionary language filters must not be empty");
  });

  it("requests bounded suggestions with the same prefixed API client", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        prefix: "ex",
        suggestions: ["exam", "example"],
        lookupTimeMs: 3,
      }),
    );
    const client = new DictionaryClient({
      baseUrl: "/speak/mdict/api/v1/",
      fetch: fetchMock,
    });

    await expect(
      client.suggestions(" ex ", {
        dictionaryIds: ["one", "two"],
        limit: 12,
      }),
    ).resolves.toEqual({
      prefix: "ex",
      suggestions: ["exam", "example"],
      lookupTimeMs: 3,
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/speak/mdict/api/v1/suggestions?prefix=ex&limit=12&dictionary_ids=one%2Ctwo",
    );
  });

  it("rejects blank suggestion prefixes and out-of-contract limits", async () => {
    const client = new DictionaryClient({ fetch: vi.fn() });

    await expect(client.suggestions("  ")).rejects.toThrow(
      "Suggestion prefix must not be empty",
    );
    await expect(client.suggestions("ex", { limit: 101 })).rejects.toThrow(
      "Suggestion limit must be an integer between 1 and 100",
    );
  });

  it("surfaces nested backend error messages", async () => {
    const client = new DictionaryClient({
      fetch: vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ error: { message: "Unsupported dictionary" } }, 422),
        ),
    });

    await expect(client.listDictionaries()).rejects.toMatchObject({
      name: "DictionaryApiError",
      status: 422,
      message: "Unsupported dictionary",
    });
  });
});
