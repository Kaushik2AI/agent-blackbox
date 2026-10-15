/**
 * Typed client for the FastAPI health endpoints.
 *
 * Every result is derived from a real HTTP response. If the request fails, the UI gets
 * an explicit "unreachable" state with the reason; nothing defaults to success.
 */

export type CheckResult = { ok: boolean; latency_ms: number; detail: string };

export type Readiness = {
  status: "ready" | "not_ready";
  checks: Record<string, CheckResult>;
};

export type Health = { status: "ok"; service: string; environment: string };

export type ConnectivityState =
  | { kind: "ready"; health: Health; readiness: Readiness; checkedAt: Date }
  | { kind: "degraded"; health: Health; readiness: Readiness; checkedAt: Date }
  | { kind: "unreachable"; reason: string; checkedAt: Date };

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export function backendBase(): string {
  return `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/backend`;
}

function isReadiness(value: unknown): value is Readiness {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    (v.status === "ready" || v.status === "not_ready") &&
    typeof v.checks === "object" &&
    v.checks !== null
  );
}

function isHealth(value: unknown): value is Health {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).status === "ok"
  );
}

async function getJson(fetchImpl: FetchLike, url: string, timeoutMs: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, { signal: controller.signal, cache: "no-store" });
    const contentType = res.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      throw new Error(`${url} returned HTTP ${res.status} (non-JSON); is the API running?`);
    }
    return { status: res.status, body: (await res.json()) as unknown };
  } finally {
    clearTimeout(timer);
  }
}

export async function checkConnectivity(
  fetchImpl: FetchLike = fetch,
  base: string = backendBase(),
  timeoutMs = 5000,
): Promise<ConnectivityState> {
  const checkedAt = new Date();
  try {
    const health = await getJson(fetchImpl, `${base}/healthz`, timeoutMs);
    if (health.status !== 200 || !isHealth(health.body)) {
      return { kind: "unreachable", reason: `healthz returned HTTP ${health.status}`, checkedAt };
    }
    // /readyz legitimately answers 503 with a JSON body when a dependency is down.
    const ready = await getJson(fetchImpl, `${base}/readyz`, timeoutMs);
    if (!isReadiness(ready.body)) {
      return { kind: "unreachable", reason: `readyz returned an unexpected body`, checkedAt };
    }
    return {
      kind: ready.body.status === "ready" ? "ready" : "degraded",
      health: health.body,
      readiness: ready.body,
      checkedAt,
    };
  } catch (err) {
    const reason =
      err instanceof Error
        ? err.name === "AbortError"
          ? `timed out after ${timeoutMs} ms`
          : err.message
        : String(err);
    return { kind: "unreachable", reason, checkedAt };
  }
}
