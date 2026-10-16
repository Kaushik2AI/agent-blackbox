"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type CheckpointOut,
  type ExecutionDetail,
  liveApi,
  type ReplayJob,
  type ReplayRequest,
  replayApi,
  type SuggestedFix,
  type Timeline,
} from "@/lib/api";
import { toolTitle } from "@/lib/describe";
import { href, shortId } from "@/lib/format";
import { toolNoun } from "@/lib/story";
import { useApi } from "@/lib/use-api";
import { useViewMode } from "@/lib/view-mode";
import { BTN_PRIMARY, BTN_QUIET, BTN_SECONDARY, Card, ErrorBox, Icon, Loading, Pill, StatusBadge, Tag } from "./ui";

function uniqueId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

type Loaded = { detail: ExecutionDetail; checkpoints: CheckpointOut[]; timeline: Timeline; fix: SuggestedFix | null };
type Kind = "replace_tool_argument" | "replace_tool_result" | "none";
type Obj = Record<string, unknown>;

async function load(id: string): Promise<Loaded> {
  const [detail, checkpoints, timeline] = await Promise.all([api.execution(id), replayApi.checkpoints(id), api.timeline(id)]);
  const fix = detail.status === "failed" ? await liveApi.suggestedFix(id).catch(() => null) : null;
  return { detail, checkpoints, timeline, fix };
}

export function ReplayStudio({ id }: { id: string }) {
  const { data, error, loading, reload } = useApi(() => load(id), id);
  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-5 sm:px-6">
      <p className="mb-3">
        <a href={href(`/runs/${id}`)} className="inline-flex items-center gap-1 text-[14px] text-fg-2 hover:text-fg">
          <Icon name="arrow" className="h-3.5 w-3.5 rotate-180" />Back to the run
        </a>
      </p>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[30px] font-semibold leading-9 tracking-tight">Replay Studio</h1>
          <p className="mt-0.5 max-w-2xl text-fg-2">
            Restart this run from a saved step, change one thing, and watch what the agent does next. The original run is never touched.
          </p>
        </div>
      </div>
      {loading && !data && <Card><Loading /></Card>}
      {error && <Card><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Studio data={data} />}
    </main>
  );
}

function parseObj(text: string): { ok: true; value: Obj } | { ok: false; error: string } {
  try {
    const v: unknown = JSON.parse(text);
    if (typeof v !== "object" || v === null || Array.isArray(v)) return { ok: false, error: "must be a JSON object" };
    return { ok: true, value: v as Obj };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "invalid JSON" };
  }
}

function show(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** Plain list of what changes: "remove product_name", "set sku to SKU-RED-004". */
function describeDiff(before: Obj, after: Obj): string[] {
  const out: string[] = [];
  for (const k of Object.keys(before)) if (!(k in after)) out.push(`remove ${k}`);
  for (const [k, v] of Object.entries(after)) {
    if (!(k in before)) out.push(`add ${k} = ${show(v)}`);
    else if (JSON.stringify(before[k]) !== JSON.stringify(v)) out.push(`set ${k} to ${show(v)}`);
  }
  return out;
}

function Studio({ data }: { data: Loaded }) {
  const { detail, checkpoints, timeline, fix } = data;
  const [mode] = useViewMode();
  const eligible = checkpoints.filter((c) => c.eligible);
  const firstFailing = useMemo(() => {
    const failingSpans = new Set(timeline.events.filter((e) => e.status === "error" && e.tool_name).map((e) => e.span_id));
    return eligible.find((c) => c.target_span_id && failingSpans.has(c.target_span_id)) ?? eligible[0];
  }, [eligible, timeline]);
  const failingSpans = useMemo(
    () => new Set(timeline.events.filter((e) => e.status === "error" && e.tool_name).map((e) => e.span_id)),
    [timeline],
  );

  const [checkpointId, setCheckpointId] = useState<string>(firstFailing?.checkpoint_id ?? "");
  const checkpoint = checkpoints.find((c) => c.checkpoint_id === checkpointId) ?? null;
  const targets = checkpoints.filter((c) => checkpoint && c.step_index >= checkpoint.step_index && c.target_span_id);
  const [targetSpan, setTargetSpan] = useState<string>(firstFailing?.target_span_id ?? "");
  const target = checkpoints.find((c) => c.target_span_id === targetSpan) ?? null;
  const [kind, setKind] = useState<Kind>("replace_tool_argument");
  const [text, setText] = useState<string>(JSON.stringify(firstFailing?.recorded_arguments ?? {}, null, 2));
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<ReplayJob | null>(null);
  const skipReset = useRef(false);

  const recordedOutput = useMemo(() => {
    const end = timeline.events.find((e) => e.span_id === targetSpan && e.event_type === "tool_call_end");
    return (end?.payload.output as Obj | undefined) ?? {};
  }, [timeline, targetSpan]);
  const original: Obj = kind === "replace_tool_result" ? recordedOutput : (target?.recorded_arguments ?? {});

  // Reset the change whenever the target or kind changes (unless a suggested fix set it).
  useEffect(() => {
    if (skipReset.current) {
      skipReset.current = false;
      return;
    }
    if (kind === "replace_tool_argument") setText(JSON.stringify(target?.recorded_arguments ?? {}, null, 2));
    else if (kind === "replace_tool_result") setText(JSON.stringify(recordedOutput, null, 2));
  }, [targetSpan, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = useMemo(() => (kind === "none" ? { ok: true as const, value: {} as Obj } : parseObj(text)), [text, kind]);
  const changes = parsed.ok && kind !== "none" ? describeDiff(original, parsed.value) : [];

  if (eligible.length === 0) {
    return (
      <Card>
        <div className="px-5 py-5" data-testid="replay-unavailable" role="status">
          <p className="text-[17px] font-semibold">This run can&apos;t be restarted</p>
          <p className="mt-1 text-fg-2">It was recorded without its data (metadata-only), so there is no saved state to restart from. Runs started from the live demo always can be.</p>
          <ul className="mt-2 list-inside list-disc text-[13.5px] text-fg-3">
            {checkpoints.length === 0 && <li>No saved steps were recorded.</li>}
            {[...new Set(checkpoints.flatMap((c) => c.reasons))].map((r) => <li key={r}>{r}</li>)}
          </ul>
          <button type="button" disabled className={`${BTN_PRIMARY} mt-4`}>Start re-run</button>
        </div>
      </Card>
    );
  }

  const fixReady = fix && fix.available ? fix : null;
  const applyFix = () => {
    if (!fixReady) return;
    const cp = checkpoints.find((c) => c.checkpoint_id === fixReady.request.checkpoint_id);
    if (!cp) return;
    skipReset.current = true;
    setCheckpointId(cp.checkpoint_id);
    setTargetSpan(fixReady.request.intervention.target_span_id);
    const iv = fixReady.request.intervention;
    setKind(iv.type);
    setText(JSON.stringify(iv.type === "replace_tool_argument" ? iv.arguments : iv.result, null, 2));
  };

  const changed = kind === "none" || changes.length > 0;
  const ready = checkpoint?.eligible && parsed.ok && changed && (kind === "none" || targetSpan) && !job;
  const request = (): ReplayRequest => ({
    source_execution_id: detail.id,
    checkpoint_id: checkpointId,
    mode: "deterministic",
    sandbox: "fixture_only",
    intervention:
      kind === "none" || !parsed.ok
        ? null
        : kind === "replace_tool_argument"
          ? { type: kind, target_span_id: targetSpan, arguments: parsed.value }
          : { type: kind, target_span_id: targetSpan, result: parsed.value },
    idempotency_key: `ui-${detail.id}-${uniqueId()}`,
  });
  const submit = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const res = await replayApi.submit(request());
      setJob(res.data);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };
  const isLLM = String(detail.agent_version.model_name).startsWith("llm:");
  const stage = job ? 3 : changed && parsed.ok ? 3 : 2;

  return (
    <div className="space-y-4">
      <Stepper current={stage} />

      <Card title="1. Pick where to restart" aside={<span className="text-[13px] text-fg-3">The agent resumes from the saved state just before this step.</span>}>
        <div className="path-scroll overflow-x-auto">
          <ol className="flex min-w-max items-start px-3 pb-3 pt-1" role="radiogroup" aria-label="Restart point">
            {checkpoints.map((c, i) => {
              const on = c.checkpoint_id === checkpointId;
              const failed = c.target_span_id ? failingSpans.has(c.target_span_id) : false;
              return (
                <li key={c.checkpoint_id} className="relative w-[210px] shrink-0">
                  <div className="relative flex h-9 items-center">
                    {i > 0 && <span aria-hidden className="absolute left-0 top-1/2 w-6 border-t-2 border-line-strong" />}
                    {i < checkpoints.length - 1 && <span aria-hidden className="absolute left-6 right-0 top-1/2 border-t-2 border-line-strong" />}
                    <span className={`relative z-10 ml-6 h-4 w-4 -translate-x-1/2 rounded-full border-2 ${on ? "border-context bg-context ring-4 ring-context-tint" : failed ? "border-bad bg-surface" : "border-fg-3 bg-surface"}`} />
                  </div>
                  <label data-testid="checkpoint-option" data-step={c.step_index} data-eligible={c.eligible}
                    className={`mr-3 block rounded-[10px] border p-2.5 ${c.eligible ? "cursor-pointer" : "cursor-not-allowed opacity-50"} ${on ? "border-context bg-context-tint/50" : "border-line hover:border-line-strong"}`}>
                    <input type="radio" name="checkpoint" className="sr-only" disabled={!c.eligible || !!job} checked={on}
                      onChange={() => { setCheckpointId(c.checkpoint_id); setTargetSpan(c.target_span_id ?? ""); }} />
                    <span className="flex items-center justify-between text-[12.5px] text-fg-3">
                      <span>Before step {c.step_index + 1}</span>
                      {on && <Pill tone="context">Restart here</Pill>}
                    </span>
                    <span className="mt-1 block text-[14px] font-medium leading-snug">{toolTitle(c.tool_name ?? "?", c.recorded_arguments ?? {})}</span>
                    {failed && <span className="mt-0.5 block text-[12.5px] text-bad">failed in the original</span>}
                    {mode === "technical" && <span className="mt-1 block"><Tag tone="muted">{c.tool_name}</Tag></span>}
                    {!c.eligible && <span className="mt-1 block text-[12px] text-bad">{c.reasons.join("; ")}</span>}
                  </label>
                </li>
              );
            })}
          </ol>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Card title="2. Change one thing" aside={fixReady && !job ? (
          <button type="button" onClick={applyFix} className={BTN_QUIET} data-testid="use-suggested-fix">
            <Icon name="spark" className="h-3.5 w-3.5" />Use the suggested fix
          </button>
        ) : undefined}>
          <div className="space-y-3 p-4">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="What to change">
              {([
                ["replace_tool_argument", "What the agent sends"],
                ["replace_tool_result", "What the tool answers"],
                ["none", "Nothing, just re-run"],
              ] as const).map(([k, label]) => (
                <label key={k} className={`cursor-pointer rounded-[8px] border px-3 py-1.5 text-[14px] ${kind === k ? "border-fg bg-surface font-medium" : "border-line text-fg-2 hover:border-line-strong"}`}>
                  <input type="radio" name="kind" className="sr-only" checked={kind === k} disabled={!!job} onChange={() => setKind(k)} />
                  {label}
                </label>
              ))}
            </div>
            {kind !== "none" && (
              <>
                <label className="flex items-center gap-2 text-[14px] text-fg-2">Step to change
                  <select aria-label="Target tool call" value={targetSpan} disabled={!!job} onChange={(e) => setTargetSpan(e.target.value)}
                    className="rounded-[8px] border border-line-strong bg-surface px-2 py-1 text-fg">
                    {targets.map((t) => (
                      <option key={t.target_span_id} value={t.target_span_id ?? ""}>Step {t.step_index + 1}: {toolTitle(t.tool_name ?? "?", t.recorded_arguments ?? {})}</option>
                    ))}
                  </select>
                </label>
                {mode === "technical" ? (
                  <label className="block">
                    <span className="text-[13px] text-fg-2">{kind === "replace_tool_argument" ? "Send this instead" : "Answer with this instead"} (JSON, checked against the tool&apos;s contract)</span>
                    <textarea aria-label="Intervention JSON" data-testid="intervention-editor" value={text} disabled={!!job}
                      onChange={(e) => setText(e.target.value)} rows={7} spellCheck={false}
                      className="mt-1 w-full rounded-[8px] border border-line bg-well px-3 py-2 font-mono text-[12.5px]" />
                  </label>
                ) : parsed.ok ? (
                  <FieldEditor original={original} value={parsed.value} disabled={!!job}
                    onChange={(v) => setText(JSON.stringify(v, null, 2))} noun={kind === "replace_tool_argument" ? `sent to the ${toolNoun(target?.tool_name)}` : `answered by the ${toolNoun(target?.tool_name)}`} />
                ) : (
                  <p className="text-[14px] text-bad">This change isn&apos;t valid JSON. Switch to Technical view to fix it.</p>
                )}
                {!parsed.ok && mode === "technical" && <p role="alert" className="text-[13px] text-bad">Invalid JSON: {parsed.error}</p>}
              </>
            )}
            {kind === "none" && <p className="text-[14px] text-fg-2">The agent restarts from the saved step with nothing changed. Useful to check whether a run is repeatable.</p>}
          </div>
        </Card>

        <Card title="3. Review and run">
          <div className="space-y-3 p-4">
            <p className="text-[15.5px] leading-6" data-testid="replay-summary">
              Restart before <b>step {(checkpoint?.step_index ?? 0) + 1}</b>
              {kind === "none" ? " with nothing changed." : changes.length ? <>, then at step {(target?.step_index ?? 0) + 1} {changes.join(", ")}.</> : ". Make a change on the left first."}
            </p>
            <ul className="space-y-1 text-[13.5px] text-fg-2" data-testid="sandbox-assurance">
              {[
                "A new recording, linked to this run. This run is never edited.",
                "Simulated tools only. Replies and decisions go to a throwaway sandbox.",
                `Internet access is blocked${isLLM ? ", except for the AI model itself" : ""}.`,
                isLLM ? "The AI decides again after the change, so results can vary." : "The scripted agent repeats exactly, so the result is exact.",
                "Pass or fail is decided by an outcome check that knows the right answer.",
              ].map((t) => (
                <li key={t} className="flex gap-2"><Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-ok" />{t}</li>
              ))}
            </ul>
            {submitError && <p role="alert" className="rounded-[8px] bg-bad-tint px-3 py-2 text-[14px] text-bad">{submitError}</p>}
            {!job && (
              <button type="button" disabled={!ready || submitting} onClick={submit} data-testid="replay-submit" className={`${BTN_PRIMARY} w-full py-2.5`}>
                {submitting ? "Starting…" : "Start re-run"}
              </button>
            )}
            {job && <JobProgress initial={job} sourceSteps={detail.tool_calls} />}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Stepper({ current }: { current: number }) {
  const items = ["Restart point", "Change one thing", "Review and run"];
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[14px]" aria-label="Steps">
      {items.map((t, i) => {
        const n = i + 1;
        const done = n < current;
        const on = n === current;
        return (
          <li key={t} className="flex items-center gap-2">
            <span className={`num flex h-6 w-6 items-center justify-center rounded-full text-[12.5px] ${done ? "bg-ok text-white" : on ? "bg-fg text-white" : "bg-well text-fg-2"}`}>
              {done ? <Icon name="check" className="h-3.5 w-3.5" /> : n}
            </span>
            <span className={on ? "font-semibold" : "text-fg-2"}>{t}</span>
            {n < items.length && <span aria-hidden className="mx-1 h-px w-10 bg-line-strong" />}
          </li>
        );
      })}
    </ol>
  );
}

function FieldEditor({ original, value, onChange, disabled, noun }: {
  original: Obj; value: Obj; onChange: (v: Obj) => void; disabled: boolean; noun: string;
}) {
  const keys = [...new Set([...Object.keys(original), ...Object.keys(value)])];
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const coerce = (s: string, like: unknown): unknown => {
    if (typeof like === "number" && s.trim() !== "" && !Number.isNaN(Number(s))) return Number(s);
    if (typeof like === "boolean") return s === "true";
    return s;
  };
  return (
    <div className="rounded-[10px] border border-line" data-testid="field-editor">
      <div className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto] gap-2 border-b border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg-2">
        <span>Field {noun}</span><span>Recorded</span><span>Re-run with</span><span />
      </div>
      {keys.map((k) => {
        const inNew = k in value;
        const inOld = k in original;
        const changed = !inOld || !inNew || JSON.stringify(original[k]) !== JSON.stringify(value[k]);
        return (
          <div key={k} className={`grid grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto] items-center gap-2 border-b border-line px-3 py-1.5 last:border-b-0 ${changed ? "bg-context-tint/40" : ""}`}>
            <span className="truncate font-mono text-[12.5px]">{k}</span>
            <span className={`truncate font-mono text-[12.5px] ${inOld && changed ? "text-fg-3 line-through" : "text-fg-2"}`}>{inOld ? show(original[k]) : "not sent"}</span>
            {inNew ? (
              <input aria-label={`New value for ${k}`} value={show(value[k])} disabled={disabled}
                onChange={(e) => onChange({ ...value, [k]: coerce(e.target.value, original[k]) })}
                className="min-w-0 rounded-[6px] border border-line-strong bg-surface px-2 py-1 font-mono text-[12.5px]" />
            ) : (
              <span className="text-[12.5px] text-bad">removed</span>
            )}
            {inNew ? (
              <button type="button" disabled={disabled} className={BTN_QUIET} onClick={() => { const n = { ...value }; delete n[k]; onChange(n); }}>Remove</button>
            ) : (
              <button type="button" disabled={disabled} className={BTN_QUIET} onClick={() => onChange({ ...value, [k]: original[k] })}>Restore</button>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2 bg-canvas/60 px-3 py-2">
        <input aria-label="New field name" placeholder="field name" value={newKey} disabled={disabled} onChange={(e) => setNewKey(e.target.value)}
          className="w-36 rounded-[6px] border border-line-strong bg-surface px-2 py-1 font-mono text-[12.5px]" />
        <input aria-label="New field value" placeholder="value" value={newVal} disabled={disabled} onChange={(e) => setNewVal(e.target.value)}
          className="min-w-0 flex-1 rounded-[6px] border border-line-strong bg-surface px-2 py-1 font-mono text-[12.5px]" />
        <button type="button" disabled={disabled || !newKey.trim()} className={BTN_SECONDARY}
          onClick={() => { onChange({ ...value, [newKey.trim()]: newVal }); setNewKey(""); setNewVal(""); }}>
          Add field
        </button>
      </div>
    </div>
  );
}

function JobProgress({ initial, sourceSteps }: { initial: ReplayJob; sourceSteps: number }) {
  const [job, setJob] = useState(initial);
  const [pollError, setPollError] = useState<string | null>(null);
  useEffect(() => {
    if (job.status === "succeeded" || job.status === "failed") return;
    const t = setInterval(async () => {
      try {
        setJob(await replayApi.job(initial.job_id));
        setPollError(null);
      } catch (e) {
        setPollError(e instanceof Error ? e.message : String(e));
      }
    }, 1000);
    return () => clearInterval(t);
  }, [job.status, initial.job_id]);

  const passed = job.result.fork_verifier_passed as boolean | undefined;
  const forkCalls = (job.result.fork_tool_calls as number | undefined) ?? null;
  return (
    <div className="space-y-3 border-t border-line pt-3" aria-live="polite" data-testid="replay-job" data-status={job.status}>
      {(job.status === "queued" || job.status === "running") && (
        <p className="flex items-center gap-2 text-context"><span className="rec-dot h-2.5 w-2.5 rounded-full bg-context" />Re-running… If this never finishes, the background worker isn&apos;t running.</p>
      )}
      {pollError && <p className="text-xs text-bad">{pollError}</p>}
      {job.status === "failed" && <p role="alert" className="text-bad">{job.error}</p>}
      {job.status === "succeeded" && (
        <>
          <p data-testid="fork-verdict" className={`text-[17px] font-semibold ${passed ? "text-ok" : "text-bad"}`}>
            {passed ? "Fixed by one change: passed" : "Still failing after this change: failed"}
          </p>
          <div className="flex items-center gap-2 text-[13.5px]">
            <span className="flex items-center gap-1.5"><StatusBadge status="failed" /><span className="num text-fg-2">{sourceSteps} steps</span></span>
            <Icon name="arrow" className="h-4 w-4 text-fg-3" />
            <span className="flex items-center gap-1.5"><StatusBadge status={passed ? "succeeded" : "failed"} />
              {forkCalls !== null && <span className="num text-fg-2">{forkCalls + job.checkpoint_step_index} steps</span>}
            </span>
            <span className="ml-auto font-mono text-[11.5px] text-fg-3">re-run {shortId(job.fork_execution_id)}</span>
          </div>
          {!passed && Array.isArray(job.result.fork_verifier_reasons) && (
            <p className="text-[13px] text-fg-2">Outcome check: {(job.result.fork_verifier_reasons as string[]).join(", ")}</p>
          )}
          <div className="flex flex-wrap gap-2">
            <a href={href(`/replays/${job.job_id}`)} data-testid="open-comparison" className={BTN_PRIMARY}>Compare before and after</a>
            <a href={href(`/runs/${job.fork_execution_id}`)} className={BTN_SECONDARY}>Open the re-run</a>
          </div>
        </>
      )}
    </div>
  );
}
