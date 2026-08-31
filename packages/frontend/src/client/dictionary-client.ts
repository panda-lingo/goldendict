import type {
  DictionaryClientOptions,
  DictionarySummary,
  LookupOptions,
  LookupResponse,
  SuggestionsOptions,
  SuggestionsResponse,
} from "../types";

export class DictionaryApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "DictionaryApiError";
    this.status = status;
    this.body = body;
  }
}

type DictionaryLike = Partial<DictionarySummary> & {
  dictionaryId?: string;
  dictionaryName?: string;
};

function normalizeBaseUrl(baseUrl: string): string {
  const normalized = baseUrl.trim() || "/api/v1";
  return normalized.length > 1 ? normalized.replace(/\/+$/, "") : normalized;
}

function normalizeDictionary(value: DictionaryLike): DictionarySummary {
  const id = value.id ?? value.dictionaryId;
  const name = value.name ?? value.dictionaryName;
  if (!id || !name) {
    throw new TypeError("Dictionary response is missing id or name");
  }
  return {
    id,
    name,
    format: value.format ?? "unknown",
    ...(value.sourceLanguage
      ? { sourceLanguage: value.sourceLanguage }
      : {}),
    ...(value.targetLanguage
      ? { targetLanguage: value.targetLanguage }
      : {}),
    ...(value.path ? { path: value.path } : {}),
    ...(value.iconUrl ? { iconUrl: value.iconUrl } : {}),
    ...(value.resourceBaseUrl
      ? { resourceBaseUrl: value.resourceBaseUrl }
      : {}),
    ...(value.wordCount !== undefined ? { wordCount: value.wordCount } : {}),
  };
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export class DictionaryClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly headers: Readonly<Record<string, string>>;
  private readonly credentials: RequestCredentials;

  constructor(options: DictionaryClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? "/api/v1");
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (!fetchImpl) {
      throw new TypeError("A fetch implementation is required");
    }
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.headers = options.headers ?? {};
    this.credentials = options.credentials ?? "same-origin";
  }

  async listDictionaries(signal?: AbortSignal): Promise<DictionarySummary[]> {
    const body = await this.request<
      DictionaryLike[] | { dictionaries: DictionaryLike[] }
    >("/dictionaries", { signal });
    const dictionaries = Array.isArray(body) ? body : body.dictionaries;
    return dictionaries.map(normalizeDictionary);
  }

  async lookup(word: string, options: LookupOptions = {}): Promise<LookupResponse> {
    const normalizedWord = word.trim();
    if (!normalizedWord) {
      throw new TypeError("Lookup word must not be empty");
    }
    const query = new URLSearchParams();
    if (options.dictionaryIds?.length) {
      query.set("dictionary_ids", options.dictionaryIds.join(","));
    }
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    const response = await this.request<LookupResponse>(
      `/lookup/${encodeURIComponent(normalizedWord)}${suffix}`,
      { signal: options.signal },
    );
    return {
      word: response.word,
      articles: response.articles ?? [],
      suggestions: response.suggestions ?? [],
      lookupTimeMs: response.lookupTimeMs ?? 0,
    };
  }

  async suggestions(
    prefix: string,
    options: SuggestionsOptions = {},
  ): Promise<SuggestionsResponse> {
    const normalizedPrefix = prefix.trim();
    if (!normalizedPrefix) {
      throw new TypeError("Suggestion prefix must not be empty");
    }
    const limit = options.limit ?? 20;
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      throw new RangeError("Suggestion limit must be an integer between 1 and 100");
    }
    const query = new URLSearchParams({
      prefix: normalizedPrefix,
      limit: String(limit),
    });
    if (options.dictionaryIds?.length) {
      query.set("dictionary_ids", options.dictionaryIds.join(","));
    }
    const response = await this.request<SuggestionsResponse>(
      `/suggestions?${query.toString()}`,
      { signal: options.signal },
    );
    return {
      prefix: response.prefix ?? normalizedPrefix,
      suggestions: response.suggestions ?? [],
      lookupTimeMs: response.lookupTimeMs ?? 0,
    };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      credentials: this.credentials,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...this.headers,
        ...init.headers,
      },
    });
    const body = await readResponseBody(response);
    if (!response.ok) {
      let serverMessage = response.statusText;
      if (typeof body === "object" && body) {
        if ("message" in body) {
          serverMessage = String((body as { message: unknown }).message);
        } else if (
          "error" in body &&
          typeof (body as { error: unknown }).error === "object" &&
          (body as { error: object | null }).error &&
          "message" in (body as { error: object }).error
        ) {
          serverMessage = String(
            (body as { error: { message: unknown } }).error.message,
          );
        }
      }
      throw new DictionaryApiError(
        serverMessage || `Dictionary request failed (${response.status})`,
        response.status,
        body,
      );
    }
    return body as T;
  }
}
