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
  overview: (since?: string, project?: string) => apiGet<Overview>("/api/v1/overview", { since, project }),
  agentVersions: () => apiGet<AgentVersion[]>("/api/v1/agent-versions"),
  executions: (filters: {
    status?: string;
    agent_version_id?: string;
    project?: string;
    since?: string;
    limit?: number;
    offset?: number;
  }) => apiGet<ExecutionPage>("/api/v1/executions", filters),
  execution: (id: string) => apiGet<ExecutionDetail>(`/api/v1/executions/${id}`),
  timeline: (id: string) => apiGet<Timeline>(`/api/v1/executions/${id}/timeline`),
  graph: (id: string) => apiGet<Graph>(`/api/v1/executions/${id}/graph`),
};

// ------------------------------------------------------------------ M5 findings
export type Finding = {
  id: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  explanation: string;
  evidence_event_ids: string[];
  evidence_span_ids: string[];
  caveats: string[];
  detector: string;
  detector_version: string;
  kind: "verified" | "hypothesis";
};

export type FindingsOut = { execution_id: string; findings: Finding[]; note: string };

// ------------------------------------------------------------------ M6/M7 replay
export type CheckpointOut = {
  checkpoint_id: string;
  step_index: number;
  node_id: string;
  target_span_id: string | null;
  tool_name: string | null;
  recorded_arguments: Record<string, unknown> | null;
  replay_capability: string;
  eligible: boolean;
  reasons: string[];
};

export type ReplayJob = {
  job_id: string;
  source_execution_id: string;
  fork_execution_id: string;
  checkpoint_id: string;
  checkpoint_step_index: number;
  status: "queued" | "running" | "succeeded" | "failed";
  replay_mode: string;
  replay_level: "checkpoint_replay" | "controlled_counterfactual";
  intervention: Record<string, unknown> | null;
  sandbox: Record<string, unknown>;
  attempts: number;
  error: string | null;
  result: Record<string, unknown>;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ReplayRequest = {
  source_execution_id: string;
  checkpoint_id: string;
  mode: "deterministic";
  sandbox: "fixture_only";
  intervention: null | {
    type: "replace_tool_argument" | "replace_tool_result";
    target_span_id: string;
    arguments?: Record<string, unknown>;
    result?: Record<string, unknown>;
  };
  idempotency_key: string;
};

export type ComparisonStep = {
  call_index: number;
  inherited: boolean;
  changed: boolean;
  intervened: boolean;
  source: StepSide | null;
  fork: StepSide | null;
};
export type StepSide = {
  tool: string | null;
  status: string | null;
  arguments: unknown;
  error_code: string | null;
  span_id: string | null;
  intervention: string | null;
};
export type ComparisonSide = {
  execution_id: string;
  status: string;
  verifier: { passed?: boolean; reasons?: string[] } | null;
  termination: string | null;
  metrics: Record<string, number | null>;
  error_codes: string[];
  findings: { category: string; severity: string; title: string }[];
};
export type Comparison = {
  job_id: string;
  replay_mode: string;
  replay_level: string;
  checkpoint: { checkpoint_id: string; step_index: number };
  intervention: Record<string, unknown> | null;
  sandbox: Record<string, unknown>;
  source: ComparisonSide;
  fork: ComparisonSide;
  steps: ComparisonStep[];
  first_divergence_call_index: number | null;
  state_diff: { path: string; source: unknown; fork: unknown; change: string }[] | null;
  state_diff_note: string | null;
  outcome_changed: boolean;
  caveat: string;
};

export async function apiPost<T>(path: string, body: unknown, base: string = backendBase()): Promise<{ status: number; data: T }> {
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiError(null, `Could not reach the API: ${describeError(err, 0)}`);
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const data: unknown = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = isJson && data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail : `HTTP ${res.status}`;
    const reasons = detail && typeof detail === "object" && "reasons" in (detail as object)
      ? ((detail as { reasons: string[] }).reasons).join("; ")
      : typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(res.status, reasons);
  }
  return { status: res.status, data: data as T };
}

export const replayApi = {
  findings: (id: string) => apiGet<FindingsOut>(`/api/v1/executions/${id}/findings`),
  checkpoints: (id: string) => apiGet<CheckpointOut[]>(`/api/v1/executions/${id}/checkpoints`),
  replaysOf: (id: string) => apiGet<ReplayJob[]>(`/api/v1/executions/${id}/replays`),
  job: (jobId: string) => apiGet<ReplayJob>(`/api/v1/replays/${jobId}`),
  comparison: (jobId: string) => apiGet<Comparison>(`/api/v1/replays/${jobId}/comparison`),
  submit: (req: ReplayRequest) => apiPost<ReplayJob>("/api/v1/replays", req),
};

// ------------------------------------------------------------------ live demo
export type Brain = "llm" | "scripted";

export type Scenario = {
  id: string;
  fixture_id: string;
  title: string;
  blurb: string;
  brains: Brain[];
  default_message: string;
  expected: string;
};

export type LiveConfig = {
  llm_available: boolean;
  /** none: no model configured; loading: local model still loading; offline: its server is down. */
  llm_state: "ready" | "loading" | "offline" | "none";
  llm_label: string;
  public_demo: boolean;
  message_max_chars: number;
  scenarios: Scenario[];
};

/** One record streamed by a live run (see apps/api/app/services/live.py). */
export type LiveStep =
  | {
      kind: "decision";
      action: "tool_call" | "finish";
      tool: string | null;
      args: Record<string, unknown> | null;
      reason: string | null;
      note: string | null;
      tokens: { input_tokens: number; output_tokens: number } | null;
      unparsed: boolean;
      t_ms: number;
    }
  | {
      kind: "tool";
      call_index: number;
      tool: string;
      args: Record<string, unknown>;
      ok: boolean;
      result: Record<string, unknown> | null;
      error_code: string | null;
      error: string | null;
      intervention: string | null;
      t_ms: number;
    }
  | { kind: "budget"; max_tool_calls: number; t_ms: number }
  | { kind: "end"; termination: string; verifier_passed: boolean; t_ms: number };

export type LiveRun = {
  live_id: string;
  status: "queued" | "running" | "done" | "error";
  scenario: string | null;
  brain: Brain | null;
  execution_id: string | null;
  error: string | null;
  verifier_passed: boolean | null;
  steps: LiveStep[];
  next: number;
};

export type SuggestedFix =
  | { available: false; reason: string }
  | {
      available: true;
      label: string;
      explanation: string;
      call_index: number;
      tool: string;
      before: Record<string, unknown>;
      request: {
        source_execution_id: string;
        checkpoint_id: string;
        intervention: {
          type: "replace_tool_argument" | "replace_tool_result";
          target_span_id: string;
          arguments?: Record<string, unknown>;
          result?: Record<string, unknown>;
        };
      };
    };

export const liveApi = {
  config: () => apiGet<LiveConfig>("/api/v1/live/config"),
  start: (body: { scenario: string; brain: Brain; message?: string }) =>
    apiPost<LiveRun>("/api/v1/live-runs", body),
  poll: (id: string, after: number) => apiGet<LiveRun>(`/api/v1/live-runs/${id}`, { after }),
  suggestedFix: (executionId: string) =>
    apiGet<SuggestedFix>(`/api/v1/executions/${executionId}/suggested-fix`),
  replay: (fix: Extract<SuggestedFix, { available: true }>, key: string) =>
    apiPost<ReplayJob>("/api/v1/replays", {
      ...fix.request,
      mode: "deterministic",
      sandbox: "fixture_only",
      idempotency_key: key,
    }),
};

// ------------------------------------------------------------------ benchmark (M8/M9)
export type RateOut = { k: number; n: number; rate: number | null; ci_low: number | null; ci_high: number | null };

export type EvalSource = {
  source: string;
  benchmark_version: string;
  model_spec: string;
  model_id: string;
  model_revision: string | null;
  seed: number;
  cases: number;
  runs: number;
  imported_at: string | null;
  success: RateOut;
  repair_recovery: RateOut;
};

export type EvalBlock = {
  baseline_runs: number;
  failed_runs: number;
  success: RateOut;
  repair_coverage: RateOut;
  repair_recovery: RateOut;
  random_recovery: RateOut;
  no_change_recovery: RateOut;
  replay_validity: RateOut;
  false_benefit: RateOut;
  detectors: {
    per_category: Record<string, { tp: number; fp: number; fn: number; precision: RateOut; recall: RateOut }>;
    coverage_on_failed: RateOut;
    failure_causes?: Record<string, number>;
    false_alarm_on_passed: RateOut;
  };
  latency: Record<string, { median_ms: number | null; p95_ms: number | null }>;
  tokens: Record<string, { mean_tokens: number | null; cost_usd: number | null }>;
};

export type EvalArmCell = { passed: boolean; skipped: string | null; execution_id: string | null; findings: string[] | null; intervention: string | null };

export type EvalSummary = {
  source: string;
  benchmark_version: string;
  model_spec: string;
  model_id: string;
  model_revision: string | null;
  seed: number;
  cases: number;
  runs: number;
  splits: Partial<Record<"all" | "dev" | "heldout", EvalBlock>>;
  families: { family: string; cases: number; success: RateOut; repair_recovery: RateOut; random_recovery: RateOut; replay_validity: RateOut }[];
  case_rows: { case_id: string; family: string; split: string; baseline?: EvalArmCell; repair?: EvalArmCell; no_change?: EvalArmCell; random?: boolean[] }[];
};

export const evalApi = {
  sources: () => apiGet<EvalSource[]>("/api/v1/evaluations"),
  summary: (source: string) => apiGet<EvalSummary>(`/api/v1/evaluations/${source}`),
  csvUrl: (source: string) => `${backendBase()}/api/v1/evaluations/${source}/runs.csv`,
};
