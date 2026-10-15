"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type CheckpointOut,
  type ExecutionDetail,
  type ReplayJob,
  type ReplayRequest,
  replayApi,
  type Timeline,
} from "@/lib/api";
import { href, shortId } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Card, ErrorBox, Loading, StatusBadge } from "./ui";

function uniqueId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

type Loaded = { detail: ExecutionDetail; checkpoints: CheckpointOut[]; timeline: Timeline };
type Kind = "replace_tool_argument" | "replace_tool_result" | "none";

async function load(id: string): Promise<Loaded> {
  const [detail, checkpoints, timeline] = await Promise.all([
    api.execution(id), replayApi.checkpoints(id), api.timeline(id),
  ]);
  return { detail, checkpoints, timeline };
}

export function ReplayStudio({ id }: { id: string }) {
  const { data, error, loading, reload } = useApi(() => load(id), id);
  return (
    <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
      <p className="mb-3 text-sm"><a href={href(`/runs/${id}`)} className="text-muted hover:text-[#e6edf3]">← Back to run</a></p>
      <h1 className="text-2xl font-semibold tracking-tight">Replay Studio</h1>
      <p className="mt-1 mb-6 max-w-3xl text-sm text-muted">
        Resume this run from a saved pre-step checkpoint as a <b>new</b> execution, optionally
        changing exactly one tool call. The remaining steps are re-executed for real in a
        sandbox; the original run is never modified.
      </p>
      {loading && !data && <Card><Loading /></Card>}
      {error && <Card><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Studio data={data} />}
    </main>
  );
}

function Studio({ data }: { data: Loaded }) {
  const { detail, checkpoints, timeline } = data;
  const eligible = checkpoints.filter((c) => c.eligible);
  const firstFailing = useMemo(() => {
    const failingSpans = new Set(timeline.events.filter((e) => e.status === "error" && e.tool_name).map((e) => e.span_id));
    return eligible.find((c) => c.target_span_id && failingSpans.has(c.target_span_id)) ?? eligible[0];
  }, [eligible, timeline]);

  const [checkpointId, setCheckpointId] = useState<string>(firstFailing?.checkpoint_id ?? "");
  const checkpoint = checkpoints.find((c) => c.checkpoint_id === checkpointId) ?? null;
  const targets = checkpoints.filter((c) => checkpoint && c.step_index >= checkpoint.step_index && c.target_span_id);
  const [targetSpan, setTargetSpan] = useState<string>(firstFailing?.target_span_id ?? "");
  const target = checkpoints.find((c) => c.target_span_id === targetSpan) ?? null;
  const [kind, setKind] = useState<Kind>("replace_tool_argument");
  const [text, setText] = useState<string>(JSON.stringify(firstFailing?.recorded_arguments ?? {}, null, 2));
  const [confirming, setConfirming] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [job, setJob] = useState<ReplayJob | null>(null);

  const recordedOutput = useMemo(() => {
    const end = timeline.events.find((e) => e.span_id === targetSpan && e.event_type === "tool_call_end");
    return (end?.payload.output as Record<string, unknown> | undefined) ?? {};
  }, [timeline, targetSpan]);

  // Reset the editor whenever the target or kind changes.
  useEffect(() => {
    if (kind === "replace_tool_argument") setText(JSON.stringify(target?.recorded_arguments ?? {}, null, 2));
    else if (kind === "replace_tool_result") setText(JSON.stringify(recordedOutput, null, 2));
  }, [targetSpan, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = useMemo(() => {
    if (kind === "none") return { ok: true as const, value: null };
    try {
      const v: unknown = JSON.parse(text);
      if (typeof v !== "object" || v === null || Array.isArray(v)) return { ok: false as const, error: "must be a JSON object" };
      return { ok: true as const, value: v as Record<string, unknown> };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "invalid JSON" };
    }
  }, [text, kind]);

  if (eligible.length === 0) {
    return (
      <Card>
        <div className="px-4 py-5 text-sm" data-testid="replay-unavailable" role="status">
          <p className="font-medium text-warn">Replay is not available for this run.</p>
          <ul className="mt-2 list-inside list-disc text-muted">
            {checkpoints.length === 0 && <li>No checkpoints were recorded.</li>}
            {[...new Set(checkpoints.flatMap((c) => c.reasons))].map((r) => <li key={r}>{r}</li>)}
          </ul>
          <p className="mt-3 text-muted">Record the run with content capture (e.g. <code className="font-mono">make seed-demo</code>) to make its checkpoints replayable.</p>
          <button type="button" disabled className="mt-4 rounded bg-warn/40 px-4 py-2 text-sm text-ink opacity-50">Run replay</button>
        </div>
      </Card>
    );
  }

  const ready = checkpoint?.eligible && parsed.ok && (kind === "none" || targetSpan);
  const request = (): ReplayRequest => ({
    source_execution_id: detail.id,
    checkpoint_id: checkpointId,
    mode: "deterministic",
    sandbox: "fixture_only",
    intervention:
      kind === "none" || !parsed.ok || !parsed.value
        ? null
        : kind === "replace_tool_argument"
          ? { type: kind, target_span_id: targetSpan, arguments: parsed.value }
          : { type: kind, target_span_id: targetSpan, result: parsed.value },
    idempotency_key: `ui-${detail.id}-${uniqueId()}`,
  });

  const submit = async () => {
    setSubmitError(null);
    try {
      const res = await replayApi.submit(request());
      setJob(res.data);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="1 · Checkpoint (state saved before a tool call)">
        <ul className="divide-y divide-line" role="radiogroup" aria-label="Checkpoint">
          {checkpoints.map((c) => (
            <li key={c.checkpoint_id}>
              <label data-testid="checkpoint-option" data-step={c.step_index} data-eligible={c.eligible}
                className={`flex cursor-pointer items-start gap-3 px-4 py-2.5 text-sm ${c.eligible ? "hover:bg-line/50" : "cursor-not-allowed opacity-50"}`}>
                <input type="radio" name="checkpoint" className="mt-1" disabled={!c.eligible || !!job}
                  checked={checkpointId === c.checkpoint_id}
                  onChange={() => { setCheckpointId(c.checkpoint_id); setTargetSpan(c.target_span_id ?? ""); }} />
                <span className="min-w-0">
                  <span className="font-mono">before call #{c.step_index} · {c.tool_name ?? "?"}</span>
                  <span className="ml-2 font-mono text-xs text-muted">{c.recorded_arguments ? JSON.stringify(c.recorded_arguments) : ""}</span>
                  {!c.eligible && <span className="block text-xs text-bad">{c.reasons.join("; ")}</span>}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="2 · Intervention (exactly one change)">
        <div className="space-y-3 px-4 py-3 text-sm">
          <div className="flex flex-wrap gap-4" role="radiogroup" aria-label="Intervention type">
            {([
              ["replace_tool_argument", "Replace tool arguments"],
              ["replace_tool_result", "Replace tool result"],
              ["none", "No change (plain checkpoint replay)"],
            ] as const).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2">
                <input type="radio" name="kind" checked={kind === k} disabled={!!job} onChange={() => setKind(k)} /> {label}
              </label>
            ))}
          </div>
          {kind !== "none" && (
            <>
              <label className="block text-muted">Target tool call{" "}
                <select aria-label="Target tool call" value={targetSpan} disabled={!!job}
                  onChange={(e) => setTargetSpan(e.target.value)}
                  className="ml-1 rounded border border-line bg-panel px-2 py-1 text-[#e6edf3]">
                  {targets.map((t) => (
                    <option key={t.target_span_id} value={t.target_span_id ?? ""}>call #{t.step_index} · {t.tool_name}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-muted">{kind === "replace_tool_argument" ? "New arguments" : "Result to return instead"} (JSON, validated against the tool contract by the server)</span>
                <textarea aria-label="Intervention JSON" data-testid="intervention-editor" value={text} disabled={!!job}
                  onChange={(e) => setText(e.target.value)} rows={6} spellCheck={false}
                  className="mt-1 w-full rounded border border-line bg-ink px-3 py-2 font-mono text-xs text-[#e6edf3] focus:outline-2 focus:outline-ok" />
              </label>
              {!parsed.ok && <p role="alert" className="text-xs text-bad">Invalid JSON: {parsed.error}</p>}
            </>
          )}
        </div>
      </Card>

      <Card title="3 · Sandbox">
        <ul className="space-y-1 px-4 py-3 text-sm text-muted" data-testid="sandbox-assurance">
          <li>✓ New execution with its own ID, linked to this run as its parent; this run is never edited.</li>
          <li>✓ Only the five simulated, allowlisted tools; drafts and resolutions go to a per-fork sandbox store.</li>
          <li>✓ Network access is blocked during the replay; any attempt fails the replay and is counted.</li>
          <li>✓ Mode: <span className="font-mono text-[#e6edf3]">deterministic</span> (scripted stub model, frozen fixtures, frozen agent version).</li>
          <li>✓ Success is decided by the ground-truth verifier, not by the agent.</li>
        </ul>
      </Card>

      {submitError && <Card><ErrorBox message={submitError} /></Card>}

      {!job && !confirming && (
        <button type="button" disabled={!ready} onClick={() => setConfirming(true)} data-testid="replay-submit"
          className="rounded bg-warn px-4 py-2 text-sm font-semibold text-ink hover:bg-warn/90 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-warn">
          Run replay
        </button>
      )}
      {confirming && (
        <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="rounded-lg border border-warn/60 bg-panel px-4 py-3">
          <p id="confirm-title" className="text-sm font-medium">
            Replay from checkpoint before call #{checkpoint?.step_index}
            {kind === "none" ? " with no change" : ` with ${kind.replaceAll("_", " ")} on call #${target?.step_index}`}?
          </p>
          <div className="mt-3 flex gap-2">
            <button type="button" onClick={submit} data-testid="replay-confirm" autoFocus
              className="rounded bg-warn px-3 py-1.5 text-sm font-semibold text-ink">Confirm</button>
            <button type="button" onClick={() => setConfirming(false)}
              className="rounded border border-line px-3 py-1.5 text-sm">Cancel</button>
          </div>
        </div>
      )}
      {job && <JobProgress initial={job} />}
    </div>
  );
}

function JobProgress({ initial }: { initial: ReplayJob }) {
  const [job, setJob] = useState(initial);
  const [pollError, setPollError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (job.status === "succeeded" || job.status === "failed") return;
    timer.current = setInterval(async () => {
      try {
        const next = await replayApi.job(initial.job_id);
        setJob(next);
        setPollError(null);
      } catch (e) {
        setPollError(e instanceof Error ? e.message : String(e));
      }
    }, 1000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [job.status, initial.job_id]);

  const passed = job.result.fork_verifier_passed as boolean | undefined;
  return (
    <Card title="Replay job">
      <div className="space-y-2 px-4 py-3 text-sm" aria-live="polite" data-testid="replay-job" data-status={job.status}>
        <p className="flex flex-wrap items-center gap-2">
          <StatusBadge status={job.status === "queued" || job.status === "running" ? "running" : job.status === "succeeded" ? "ok" : "error"} />
          <span className="font-mono">{job.status}</span>
          <span className="text-muted">job {shortId(job.job_id)} · fork {shortId(job.fork_execution_id)} · {job.replay_level.replaceAll("_", " ")}</span>
        </p>
        {(job.status === "queued" || job.status === "running") && (
          <p className="text-muted">Waiting for the worker… (needs the RQ worker started by <code className="font-mono">make dev</code>)</p>
        )}
        {pollError && <p className="text-xs text-bad">{pollError}</p>}
        {job.status === "failed" && <p role="alert" className="text-bad">{job.error}</p>}
        {job.status === "succeeded" && (
          <>
            <p data-testid="fork-verdict">
              Fork verifier:{" "}
              <b className={passed ? "text-ok" : "text-bad"}>{passed ? "passed" : "failed"}</b>
              {!passed && Array.isArray(job.result.fork_verifier_reasons) && (
                <span className="text-muted"> ({(job.result.fork_verifier_reasons as string[]).join(", ")})</span>
              )}
            </p>
            <div className="flex gap-3">
              <a href={href(`/replays/${job.job_id}`)} data-testid="open-comparison"
                className="rounded bg-ok/90 px-3 py-1.5 font-semibold text-ink hover:bg-ok">Compare original vs fork →</a>
              <a href={href(`/runs/${job.fork_execution_id}`)} className="rounded border border-line px-3 py-1.5 hover:bg-line">Open fork</a>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
