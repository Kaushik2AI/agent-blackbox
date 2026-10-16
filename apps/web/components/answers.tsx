"use client";

import { useEffect, useRef, useState } from "react";
import { api, liveApi, replayApi, type ReplayJob, type SuggestedFix } from "@/lib/api";
import { verdict } from "@/lib/describe";
import { href } from "@/lib/format";
import { fromTimeline, type TapeStep } from "@/lib/steps";
import { type RootCause, symptomLabel } from "@/lib/story";
import type { ViewMode } from "@/lib/view-mode";
import { FlightPath } from "./flight-path";
import { BTN_PRIMARY, BTN_QUIET, Icon, Pill, StatusBadge } from "./ui";

/**
 * The three answers that sit above every flight path:
 *   In simple words (what happened) | Most likely cause (why) | Try next (what to do)
 */
export function AnswerRow({ summary, passed, cause, mode, executionId, canFix, onJumpToStep, onFixTarget, failedSteps, expected }: {
  summary: string;
  passed: boolean;
  cause: RootCause | null;
  mode: ViewMode;
  executionId: string;
  canFix: boolean;
  onJumpToStep?: (key: string) => void;
  onFixTarget?: (call: number | null) => void;
  failedSteps: number;
  expected?: string | null;
}) {
  return (
    <div className="grid gap-3 lg:grid-cols-3" data-testid="verdict" data-passed={String(passed)}>
      <SimpleWordsCard summary={summary} passed={passed} expected={expected} />
      {passed ? (
        <PassedCard cause={cause} />
      ) : (
        <RootCauseCard cause={cause} mode={mode} onJumpToStep={onJumpToStep} />
      )}
      {passed ? (
        <NothingToFixCard executionId={executionId} />
      ) : canFix ? (
        <NextStepCard executionId={executionId} onHighlight={onFixTarget} failedBefore={failedSteps} />
      ) : (
        <StudioOnlyCard executionId={executionId} />
      )}
    </div>
  );
}

function SimpleWordsCard({ summary, passed, expected }: { summary: string; passed: boolean; expected?: string | null }) {
  return (
    <section className="rounded-[12px] border border-line bg-surface p-4" data-testid="simple-words">
      <h2 className="text-[13.5px] font-medium text-context">In simple words</h2>
      <p className="mt-1.5 text-[15.5px] leading-6">{summary}</p>
      {!passed && expected && <p className="mt-2 text-[13.5px] text-fg-2">The right outcome was: {expected}.</p>}
    </section>
  );
}

function RootCauseCard({ cause, mode, onJumpToStep }: { cause: RootCause | null; mode: ViewMode; onJumpToStep?: (key: string) => void }) {
  return (
    <section className="rounded-[12px] border border-bad/35 bg-surface p-4" data-testid="root-cause">
      <h2 className="flex items-center gap-1.5 text-[13.5px] font-medium text-bad"><Icon name="flag" className="h-3.5 w-3.5" />Most likely cause</h2>
      <p className="mt-1.5 text-[17px] font-semibold leading-6">{cause?.title ?? "No cause found"}</p>
      <p className="mt-1 text-[14px] leading-5 text-fg-2">{cause?.detail}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {cause?.step && (
          <button type="button" onClick={() => onJumpToStep?.(cause.step!.key)}
            className="inline-flex items-center gap-1 rounded-full border border-bad/40 px-2 py-0.5 text-[12.5px] font-medium text-bad hover:bg-bad-tint">
            Evidence: step {cause.step.callIndex + 1}
          </button>
        )}
        {cause?.symptoms.map((s) => (
          <Pill key={s.id} tone="neutral" title={s.explanation}>then: {symptomLabel(s.category)}</Pill>
        ))}
      </div>
      {mode === "technical" && cause?.finding && (
        <p className="mt-2 font-mono text-[11.5px] text-fg-3">detector {cause.finding.detector} v{cause.finding.detector_version}</p>
      )}
    </section>
  );
}

function PassedCard({ cause }: { cause: RootCause | null }) {
  return (
    <section className="rounded-[12px] border border-ok/35 bg-surface p-4" data-testid="root-cause">
      <h2 className="flex items-center gap-1.5 text-[13.5px] font-medium text-ok"><Icon name="check" className="h-3.5 w-3.5" />Outcome check</h2>
      <p className="mt-1.5 text-[17px] font-semibold leading-6">Handled correctly</p>
      <p className="mt-1 text-[14px] leading-5 text-fg-2">
        {cause ? "It got there, but not cleanly. See the warnings on the path." : "No problems found on the way."}
      </p>
      {cause && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Pill tone="warn">{symptomLabel(cause.category ?? "")}</Pill>
          {cause.symptoms.map((s) => <Pill key={s.id} tone="warn">{symptomLabel(s.category)}</Pill>)}
        </div>
      )}
    </section>
  );
}

function NothingToFixCard({ executionId }: { executionId: string }) {
  return (
    <section className="rounded-[12px] border border-line bg-surface p-4">
      <h2 className="text-[13.5px] font-medium text-fg-2">Try next</h2>
      <p className="mt-1.5 text-[15px] leading-6">Nothing to fix. To see how sensitive this run is, change one step and re-run it.</p>
      <a href={href(`/runs/${executionId}/replay`)} className={`${BTN_QUIET} mt-2 -ml-1.5`}>Open Replay Studio</a>
    </section>
  );
}

function StudioOnlyCard({ executionId }: { executionId: string }) {
  return (
    <section className="rounded-[12px] border border-line bg-surface p-4">
      <h2 className="text-[13.5px] font-medium text-fg-2">Try next</h2>
      <p className="mt-1.5 text-[15px] leading-6">Restart this run from any step with one change and see if it recovers.</p>
      <a href={href(`/runs/${executionId}/replay`)} className={`${BTN_PRIMARY} mt-3`}>Open Replay Studio</a>
    </section>
  );
}

// ------------------------------------------------------------------ one-click fix
type Fix = Extract<SuggestedFix, { available: true }>;
type Phase =
  | { kind: "loading" }
  | { kind: "none"; reason: string }
  | { kind: "ready"; fix: Fix }
  | { kind: "running"; fix: Fix; job: ReplayJob | null }
  | { kind: "done"; fix: Fix; job: ReplayJob; steps: TapeStep[] }
  | { kind: "error"; message: string; fix?: Fix };

function key(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

/** "Try next": the suggested change, run in one click, with the before → after result. */
export function NextStepCard({ executionId, onHighlight, failedBefore, wide = false, mode = "simple" }: {
  executionId: string; onHighlight?: (call: number | null) => void; failedBefore: number; wide?: boolean; mode?: ViewMode;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    liveApi.suggestedFix(executionId).then(
      (fix) => {
        if (!alive.current) return;
        if (fix.available) {
          setPhase({ kind: "ready", fix });
          onHighlight?.(fix.call_index);
        } else setPhase({ kind: "none", reason: fix.reason });
      },
      (err: unknown) => alive.current && setPhase({ kind: "error", message: String(err instanceof Error ? err.message : err) }),
    );
    return () => {
      alive.current = false;
    };
  }, [executionId, onHighlight]);

  async function run(fix: Fix) {
    setPhase({ kind: "running", fix, job: null });
    try {
      let { data: job } = await liveApi.replay(fix, key());
      for (let i = 0; i < 240 && (job.status === "queued" || job.status === "running"); i++) {
        if (!alive.current) return;
        setPhase({ kind: "running", fix, job });
        await new Promise((r) => setTimeout(r, 700));
        job = await replayApi.job(job.job_id);
      }
      if (job.status !== "succeeded") {
        setPhase({ kind: "error", fix, message: job.error ?? `The re-run ended as "${job.status}".` });
        return;
      }
      const tl = await api.timeline(job.fork_execution_id);
      if (alive.current) setPhase({ kind: "done", fix, job, steps: fromTimeline(tl.events) });
    } catch (err) {
      setPhase({ kind: "error", fix, message: err instanceof Error ? err.message : String(err) });
    }
  }

  return (
    <section className="rounded-[12px] border border-context/35 bg-surface p-4" data-testid="fix-panel" data-phase={phase.kind}>
      <h2 className="text-[13.5px] font-medium text-context">Try next</h2>
      {phase.kind === "loading" && <p className="mt-1.5 text-fg-2">Looking for a change that could fix it…</p>}
      {phase.kind === "none" && (
        <>
          <p className="mt-1.5 text-[15px] leading-6">{phase.reason}</p>
          <a className={`${BTN_PRIMARY} mt-3`} href={href(`/runs/${executionId}/replay`)}>Open Replay Studio</a>
        </>
      )}
      {"fix" in phase && phase.fix && (
        <>
          <p className="mt-1.5 text-[17px] font-semibold leading-6">{phase.fix.label}</p>
          <p className="mt-1 text-[14px] leading-5 text-fg-2">{phase.fix.explanation}</p>
        </>
      )}
      {phase.kind === "ready" && (
        <button type="button" className={`${BTN_PRIMARY} mt-3`} onClick={() => run(phase.fix)} data-testid="run-fix">
          Re-run from step {phase.fix.call_index + 1} with this change
        </button>
      )}
      {phase.kind === "running" && (
        <p className="mt-3 flex items-center gap-2 text-context" role="status">
          <span className="rec-dot h-2.5 w-2.5 rounded-full bg-context" />
          Re-running from step {phase.fix.call_index + 1}…{phase.job?.replay_mode === "controlled_stochastic" ? " The AI is deciding again." : ""}
        </p>
      )}
      {phase.kind === "error" && <p role="alert" className="mt-3 text-bad">{phase.message}</p>}
      {phase.kind === "done" && <FixResult phase={phase} failedBefore={failedBefore} wide={wide} mode={mode} />}
    </section>
  );
}

function FixResult({ phase, failedBefore, wide, mode }: { phase: Extract<Phase, { kind: "done" }>; failedBefore: number; wide: boolean; mode: ViewMode }) {
  const r = phase.job.result as { fork_verifier_passed?: boolean; fork_termination?: string; fork_verifier_reasons?: string[]; fork_tool_calls?: number };
  const v = verdict({ passed: r.fork_verifier_passed, termination: r.fork_termination, reasons: r.fork_verifier_reasons });
  const after = (r.fork_tool_calls ?? phase.steps.filter((s) => s.kind === "tool").length) + phase.fix.call_index;
  return (
    <div className="mt-3 border-t border-line pt-3" data-testid="fix-result" data-passed={String(v.passed)}>
      <p className={`text-[17px] font-semibold ${v.passed ? "text-ok" : "text-bad"}`}>
        {v.passed ? "Fixed by one change" : "Still failing after this change"}
      </p>
      <div className="mt-2 flex items-center gap-2 text-[13.5px]">
        <span className="flex items-center gap-1.5"><StatusBadge status="failed" /><span className="num text-fg-2">{failedBefore} steps</span></span>
        <Icon name="arrow" className="h-4 w-4 text-fg-3" />
        <span className="flex items-center gap-1.5"><StatusBadge status={v.passed ? "succeeded" : "failed"} /><span className="num text-fg-2">{after} steps</span></span>
      </div>
      {phase.job.replay_mode === "controlled_stochastic" && (
        <p className="mt-2 text-[13px] text-ai">The AI made fresh decisions after the change, so a second try can differ.</p>
      )}
      {wide && (
        <div className="mt-3">
          <p className="mb-1 text-[13px] text-fg-2">The re-run, from step {phase.fix.call_index + 1}</p>
          <FlightPath steps={phase.steps} mode={mode} testId="fix-tape" />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        <a className="text-[14px] font-medium underline underline-offset-4" href={href(`/replays/${phase.job.job_id}`)} data-testid="open-comparison">
          Compare before and after
        </a>
        <a className="text-[14px] text-fg-2 underline underline-offset-4" href={href(`/runs/${phase.job.fork_execution_id}`)}>Open the re-run</a>
      </div>
    </div>
  );
}
