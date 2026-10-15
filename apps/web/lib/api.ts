/**
 * Typed client for the FastAPI backend (reached through the Next.js /backend proxy).
 *
 * Every value rendered by the dashboard comes from one of these calls. Failures surface
 * as ApiError / an explicit "unreachable" state; nothing defaults to success or to
 * placeholder data.
 */

// ------------------------------------------------------------------ health (M1)
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
    return { kind: "unreachable", reason: describeError(err, timeoutMs), checkedAt };
  }
}

function describeError(err: unknown, timeoutMs: number): string {
  if (err instanceof Error) {
    return err.name === "AbortError" ? `timed out after ${timeoutMs} ms` : err.message;
  }
  return String(err);
}

// ------------------------------------------------------------------ data API (M3/M4)
export type ExecutionStatus = "pending" | "running" | "succeeded" | "failed" | "aborted";

export type AgentVersion = {
  id: string;
  agent: string;
  git_sha: string;
  config_hash: string;
  model_name: string;
};

export type ExecutionSummary = {
  id: string;
  project: string;
  task_id: string;
  status: ExecutionStatus;
  agent_version: AgentVersion;
  parent_execution_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  tool_calls: number;
  error_codes: string[];
  termination: string | null;
  verifier_passed: boolean | null;
};

export type ExecutionPage = {
  items: ExecutionSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type Artifact = {
  uri: string;
  sha256: string;
  type: string;
  byte_size: number | null;
  capture_policy: string;
};

export type ExecutionDetail = ExecutionSummary & {
  attributes: Record<string, unknown>;
  artifacts: Artifact[];
  span_count: number;
  event_count: number;
};

export type SpanOut = {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  kind: string;
  name: string;
  status: string;
  start_ms: number;
  end_ms: number | null;
  duration_ms: number | null;
  attributes: Record<string, unknown>;
};

export type EventOut = {
  event_id: string;
  span_id: string | null;
  sequence_no: number;
  event_type: string;
  timestamp: string;
  operation: string | null;
  tool_name: string | null;
  status: string | null;
  attributes: Record<string, unknown>;
  payload: Record<string, unknown>;
};

export type Timeline = { execution_id: string; spans: SpanOut[]; events: EventOut[] };

export type GraphNode = {
  id: string;
  kind: string;
  name: string;
  status: string;
  order: number;
  parent_span_id: string | null;
  orphan: boolean;
  duration_ms: number | null;
  tool_name: string | null;
  error_code: string | null;
};

export type GraphEdge = { id: string; source: string; target: string; kind: "parent" | "next" };

export type Graph = { execution_id: string; nodes: GraphNode[]; edges: GraphEdge[] };

export type Overview = {
  total: number;
  succeeded: number;
  failed: number;
  other: number;
  success_rate: number | null;
  median_duration_ms: number | null;
  failure_tags: Record<string, number>;
  by_task: Record<string, Record<string, number>>;
  total_tokens: number | null;
};

export class ApiError extends Error {
  constructor(
    public status: number | null,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiGet<T>(
  path: string,
  params: Record<string, string | number | undefined | null> = {},
  fetchImpl: FetchLike = fetch,
  base: string = backendBase(),
  timeoutMs = 10000,
): Promise<T> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") query.set(k, String(v));
  }
  const url = `${base}${path}${query.size ? `?${query}` : ""}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetchImpl(url, { signal: controller.signal, cache: "no-store" });
  } catch (err) {
    throw new ApiError(null, `Could not reach the API: ${describeError(err, timeoutMs)}`);
  } finally {
    clearTimeout(timer);
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const body: unknown = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail =
      isJson && body && typeof body === "object" && "detail" in body
        ? JSON.stringify((body as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  if (!isJson) throw new ApiError(res.status, `Expected JSON from ${path}; is the API running?`);
  return body as T;
}

export const api = {
  overview: (since?: string) => apiGet<Overview>("/api/v1/overview", { since }),
  agentVersions: () => apiGet<AgentVersion[]>("/api/v1/agent-versions"),
  executions: (filters: {
    status?: string;
    agent_version_id?: string;
    since?: string;
    limit?: number;
    offset?: number;
  }) => apiGet<ExecutionPage>("/api/v1/executions", filters),
  execution: (id: string) => apiGet<ExecutionDetail>(`/api/v1/executions/${id}`),
  timeline: (id: string) => apiGet<Timeline>(`/api/v1/executions/${id}/timeline`),
  graph: (id: string) => apiGet<Graph>(`/api/v1/executions/${id}/graph`),
};
