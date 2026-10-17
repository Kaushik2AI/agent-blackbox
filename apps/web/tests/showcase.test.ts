import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShowcaseError, showcaseGet, showcasePost } from "../lib/showcase";

const ex = (id: string, status: string, project: string, version = "v1") => ({
  id, status, project, task_id: "t", agent_version: { id: version }, parent_execution_id: null,
});
const intervention = { type: "replace_tool_argument", target_span_id: "s1", arguments: { sku: "SKU-1" } };
const steps = [
  { kind: "decision", t_ms: 1 },
  { kind: "tool", t_ms: 2 },
  { kind: "end", termination: "completed", verifier_passed: false, t_ms: 3 },
];
const FILES: Record<string, unknown> = {
  "index.json": {
    generated_at: "2026-10-17T00:00:00+00:00", git_sha: "abc1234", executions: [], replays: [],
    live: { bug: "e1" },
    fixes: [{ request: { source_execution_id: "e1", checkpoint_id: "c1", intervention }, job_id: "j1" }],
  },
  "executions.json": [ex("a", "failed", "demo"), ex("b", "succeeded", "demo"), ex("c", "failed", "benchmark", "v2"), ex("d", "failed", "demo")],
  "replays/j1/job.json": { job_id: "j1", status: "succeeded" },
  "live/bug.json": { live_id: "x", status: "done", scenario: "bug", brain: "scripted", execution_id: "e1", error: null, verifier_passed: false, steps, next: 3 },
};

beforeEach(() => {
  vi.stubGlobal("fetch", async (url: string) => {
    const rel = url.replace(/^.*\/snapshot\//, "");
    return rel in FILES
      ? new Response(JSON.stringify(FILES[rel]), { status: 200, headers: { "content-type": "application/json" } })
      : new Response("not found", { status: 404 });
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("showcase reads", () => {
  it("filters and pages the run list in the browser, ignoring 'since'", async () => {
    const page = await showcaseGet<{ items: { id: string }[]; total: number }>("/api/v1/executions", {
      status: "failed", project: "demo", since: "2026-01-01T00:00:00Z", limit: 1, offset: 1,
    });
    expect(page.total).toBe(2);
    expect(page.items.map((i) => i.id)).toEqual(["d"]);
    const v2 = await showcaseGet<{ items: { id: string }[] }>("/api/v1/executions", { agent_version_id: "v2" });
    expect(v2.items.map((i) => i.id)).toEqual(["c"]);
  });

  it("reports anything outside the snapshot as missing", async () => {
    await expect(showcaseGet("/api/v1/executions/zzz/timeline")).rejects.toBeInstanceOf(ShowcaseError);
    await expect(showcaseGet("/api/v1/unknown")).rejects.toMatchObject({ status: 404 });
  });
});

describe("showcase writes", () => {
  it("returns the pre-recorded re-run for exactly the suggested fix", async () => {
    const body = { checkpoint_id: "c1", source_execution_id: "e1", mode: "deterministic", idempotency_key: "k-123456",
      intervention: { arguments: { sku: "SKU-1" }, target_span_id: "s1", type: "replace_tool_argument" } };
    const { status, data } = await showcasePost<{ job_id: string }>("/api/v1/replays", body);
    expect(status).toBe(202);
    expect(data.job_id).toBe("j1");
    const other = { ...body, intervention: { ...body.intervention, arguments: { sku: "SKU-2" } } };
    await expect(showcasePost("/api/v1/replays", other)).rejects.toThrow(/Only FlightPath's suggested fix/);
  });

  it("plays a recorded scripted run back step by step; Live AI needs a server", async () => {
    vi.useFakeTimers();
    const { data } = await showcasePost<{ live_id: string; status: string; steps: unknown[]; next: number }>(
      "/api/v1/live-runs", { scenario: "bug", brain: "scripted" },
    );
    expect(data.status).toBe("running");
    expect(data.steps).toHaveLength(1);
    vi.advanceTimersByTime(600);
    const mid = await showcaseGet<{ steps: unknown[]; next: number; execution_id: string | null }>(`/api/v1/live-runs/${data.live_id}`, { after: 1 });
    expect(mid.next).toBe(2);
    expect(mid.steps).toHaveLength(1);
    expect(mid.execution_id).toBeNull();
    vi.advanceTimersByTime(2000);
    const end = await showcaseGet<{ status: string; execution_id: string }>(`/api/v1/live-runs/${data.live_id}`, { after: 2 });
    expect(end).toMatchObject({ status: "done", execution_id: "e1" });
    await expect(showcasePost("/api/v1/live-runs", { scenario: "bug", brain: "llm" })).rejects.toThrow(/run FlightPath on your own machine/);
  });
});
