export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

// A gateway in front of the API (the tunnel, Traefik during a release) answering instead of the API itself.
const GATEWAY = new Set([502, 503, 504, 520, 521, 522, 523, 524]);
const UNREACHABLE = "Rift is briefly unreachable. Try again in a moment.";
const RETRY_DELAYS = [400, 1200];

/** Safe to send twice: reads, anything carrying an idempotency key, and the on-demand market makers (one
 * shared market per key, so a repeat returns the same one). Never a bare write like redeeming an invite. */
const ON_DEMAND = /^\/events\/[^/]+\/(duels|kill-lines|draft)$/;
function repeatable(path: string, init: RequestInit): boolean {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  return method === "GET" || headers.has("Idempotency-Key") || (method === "POST" && ON_DEMAND.test(path));
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const request: RequestInit = {
    credentials: "same-origin",
    ...rest,
    headers: {
      "x-rift-client": "web",
      ...(json !== undefined ? { "content-type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  };
  const retries = repeatable(path, request) ? RETRY_DELAYS : [];
  for (let attempt = 0; ; attempt++) {
    let res: Response;
    try {
      res = await fetch(`/api/v1${path}`, request);
    } catch {
      if (attempt < retries.length) {
        await wait(retries[attempt]);
        continue;
      }
      throw new ApiError(0, "NETWORK", "Can't reach the server. Check your connection.");
    }
    const body = await res.json().catch(() => null);
    if (res.ok) return body as T;
    const err = body?.error;
    if (!err && GATEWAY.has(res.status) && attempt < retries.length) {
      await wait(retries[attempt]);
      continue;
    }
    const fallback = GATEWAY.has(res.status) ? UNREACHABLE : "Something went wrong.";
    throw new ApiError(res.status, err?.code ?? "HTTP_" + res.status, err?.message ?? fallback, err?.details ?? {});
  }
}

export const fetcher = <T,>(path: string) => api<T>(path);
