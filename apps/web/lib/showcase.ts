/**
 * Showcase mode: the web app built as static files (NEXT_PUBLIC_SHOWCASE=1), reading a
 * snapshot of a real FlightPath stack instead of calling the API. Used for the free
 * GitHub Pages deployment, which cannot run a server.
 *
 * The snapshot (infra/showcase/snapshot.py) holds every read the app makes, the scripted
 * live scenarios as recorded runs, and the suggested fix already applied to every failed
 * run. Here:
 *   - reads map onto snapshot files (list filters and paging are applied in the browser);
 *   - starting a scripted live run replays the recorded run step by step;
 *   - "Try the fix" returns the pre-recorded re-run with exactly that change;
 *   - anything that needs a server (Live AI, your own change) explains how to run locally.
 */

import type {
  ExecutionPage,
  ExecutionSummary,
  LiveConfig,
  LiveRun,
} from "./api";

export const SHOWCASE = process.env.NEXT_PUBLIC_SHOWCASE === "1";
export const REPO_URL = "https://github.com/Kaushik2AI/agent-blackbox";
export const RUN_LOCALLY = `This is the static showcase, so it can only show recorded runs. To try this, run FlightPath on your own machine: ${REPO_URL}#quickstart`;

export class ShowcaseError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ShowcaseError";
  }
}

type Fix = { request: { source_execution_id: string; checkpoint_id: string; intervention: Record<string, unknown> }; job_id: string };
type Index = { generated_at: string; git_sha: string; executions: string[]; replays: string[]; live: Record<string, string>; fixes: Fix[] };

function root(): string {
  return `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/snapshot`;
}

export function snapshotUrl(rel: string): string {
  return `${root()}/${rel}`;
}

const cache = new Map<string, Promise<unknown>>();

async function load<T>(rel: string): Promise<T> {
  let hit = cache.get(rel);
  if (!hit) {
    hit = fetch(snapshotUrl(rel)).then(async (res) => {
      if (!res.ok) {
        throw new ShowcaseError(404, res.status === 404 ? "This isn't part of the recorded showcase." : `Snapshot file returned HTTP ${res.status}`);
      }
      return res.json() as Promise<unknown>;
    });
    cache.set(rel, hit);
    hit.catch(() => cache.delete(rel));
  }
  return hit as Promise<T>;
}

const index = () => load<Index>("index.json");

// ------------------------------------------------------------------ reads
type Params = Record<string, string | number | undefined | null>;

export async function showcaseGet<T>(path: string, params: Params = {}): Promise<T> {
  const p = path.replace(/^\/+/, "/");
  let m: RegExpMatchArray | null;

  if (p === "/healthz") return (await load("health.json")) as T;
  if (p === "/readyz") {
    const idx = await index();
    return {
      status: "ready",
      checks: { snapshot: { ok: true, latency_ms: 0, detail: `static snapshot from ${idx.generated_at} (${idx.git_sha || "local build"})` } },
    } as T;
  }
  if (p === "/api/v1/live/config") return (await liveConfig()) as T;
  if (p === "/api/v1/agent-versions") return (await load("agent-versions.json")) as T;
  if (p === "/api/v1/overview") {
    const project = params.project ? String(params.project) : "all";
    return (await load(`overview/${project}.json`)) as T;
  }
  if (p === "/api/v1/executions") return (await executions(params)) as T;
  if ((m = p.match(/^\/api\/v1\/executions\/([^/]+)$/))) return (await load(`executions/${m[1]}/detail.json`)) as T;
  if ((m = p.match(/^\/api\/v1\/executions\/([^/]+)\/(timeline|graph|findings|checkpoints|replays|suggested-fix)$/))) {
    return (await load(`executions/${m[1]}/${m[2]}.json`)) as T;
  }
  if ((m = p.match(/^\/api\/v1\/replays\/([^/]+)$/))) return (await load(`replays/${m[1]}/job.json`)) as T;
  if ((m = p.match(/^\/api\/v1\/replays\/([^/]+)\/comparison$/))) return (await load(`replays/${m[1]}/comparison.json`)) as T;
  if ((m = p.match(/^\/api\/v1\/live-runs\/([^/]+)$/))) return (await pollLive(m[1], Number(params.after ?? 0))) as T;
  if (p === "/api/v1/evaluations") return (await load("evaluations.json")) as T;
  if ((m = p.match(/^\/api\/v1\/evaluations\/([^/]+)$/))) return (await load(`evaluations/${m[1]}.json`)) as T;
  throw new ShowcaseError(404, "This isn't part of the recorded showcase.");
}

async function liveConfig(): Promise<LiveConfig> {
  const cfg = await load<LiveConfig>("live-config.json");
  // No model runs here; the scripted agent replays recorded runs.
  return { ...cfg, llm_available: false, llm_state: "none", public_demo: true };
}

async function executions(params: Params): Promise<ExecutionPage> {
  const all = await load<ExecutionSummary[]>("executions.json");
  // `since` is ignored: the snapshot is a fixed moment, so "last 24 hours" would hide it.
  const rows = all.filter(
    (e) =>
      (!params.status || e.status === params.status) &&
      (!params.agent_version_id || e.agent_version.id === params.agent_version_id) &&
      (!params.project || e.project === params.project) &&
      (!params.task_id || e.task_id === params.task_id),
  );
  const limit = Number(params.limit ?? 20);
  const offset = Number(params.offset ?? 0);
  return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset };
}

// ------------------------------------------------------------------ recorded live runs
const STEP_MS = 550;
const started = new Map<string, { scenario: string; at: number }>();

async function pollLive(id: string, after: number): Promise<LiveRun> {
  const run = started.get(id);
  if (!run) throw new ShowcaseError(404, "live run not found");
  const rec = await load<LiveRun>(`live/${run.scenario}.json`);
  const visible = Math.min(rec.steps.length, 1 + Math.floor((Date.now() - run.at) / STEP_MS));
  const done = visible >= rec.steps.length;
  return {
    ...rec,
    live_id: id,
    status: done ? rec.status : "running",
    execution_id: done ? rec.execution_id : null,
    verifier_passed: done ? rec.verifier_passed : null,
    steps: rec.steps.slice(Math.min(after, visible), visible),
    next: visible,
  };
}

// ------------------------------------------------------------------ writes
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj)
      .filter((k) => obj[k] !== undefined && obj[k] !== null)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function showcasePost<T>(path: string, body: unknown): Promise<{ status: number; data: T }> {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path === "/api/v1/live-runs") {
    if (b.brain !== "scripted") throw new ShowcaseError(503, RUN_LOCALLY);
    const scenario = String(b.scenario);
    const idx = await index();
    if (!(scenario in idx.live)) throw new ShowcaseError(404, "This scenario wasn't recorded for the showcase.");
    const id = `showcase-${scenario}-${Date.now()}`;
    started.set(id, { scenario, at: Date.now() });
    return { status: 202, data: (await pollLive(id, 0)) as T };
  }
  if (path === "/api/v1/replays") {
    const idx = await index();
    const want = canonical({ s: b.source_execution_id, c: b.checkpoint_id, i: b.intervention });
    const hit = idx.fixes.find((f) => canonical({ s: f.request.source_execution_id, c: f.request.checkpoint_id, i: f.request.intervention }) === want);
    if (!hit) {
      throw new ShowcaseError(
        503,
        `Only FlightPath's suggested fix is pre-recorded here. To re-run with your own change, run FlightPath locally: ${REPO_URL}#quickstart`,
      );
    }
    return { status: 202, data: (await load(`replays/${hit.job_id}/job.json`)) as T };
  }
  throw new ShowcaseError(503, RUN_LOCALLY);
}
