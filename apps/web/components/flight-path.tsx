"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { describeStep, fmtClock } from "@/lib/describe";
import { buildBeats, type Beat, stepTitle, type ToolStep, toolNoun } from "@/lib/story";
import type { TapeStep } from "@/lib/steps";
import type { ViewMode } from "@/lib/view-mode";
import { BTN_QUIET, Disclosure, Icon, JsonBlock, Pill, Tag } from "./ui";

type Tone = "ok" | "bad" | "warn" | "muted";

/** How many of `total` steps to show when pacing a recording that arrived all at once. */
export function usePacedCount(total: number, pace: boolean): number {
  const [shown, setShown] = useState(pace ? 0 : total);
  useEffect(() => {
    if (!pace) {
      setShown(total);
      return;
    }
    if (shown >= total) return;
    const t = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 150 : 420);
    return () => clearTimeout(t);
  }, [pace, shown, total]);
  return Math.min(shown, total);
}

function toneOf(b: Beat): Tone {
  if (b.kind === "loop") return "bad";
  return describeStep(b.step).tone;
}

const TRACK: Record<Tone, string> = {
  ok: "border-solid border-line-strong",
  muted: "border-solid border-line-strong",
  warn: "border-dashed border-warn",
  bad: "border-dashed border-bad",
};

const TEXT: Record<Tone, string> = { ok: "text-ok", bad: "text-bad", warn: "text-warn", muted: "text-fg-2" };

const WIDTH = { step: "w-[236px]", loop: "w-[272px]", end: "w-[212px]" } as const;

/**
 * The run as a horizontal route: one waypoint per step, read left to right. Identical
 * failing attempts fold into one loop cluster once the run is over. The track turns red
 * and dashed after a failed step, so the moment things went wrong is visible at a glance.
 */
export function FlightPath({
  steps,
  mode,
  running = false,
  limit,
  rootKey,
  highlightCall,
  selectedKey,
  onSelect,
  testId = "tape",
  emptyText = "No steps were recorded.",
}: {
  steps: TapeStep[];
  mode: ViewMode;
  running?: boolean;
  limit?: number;
  rootKey?: string | null;
  highlightCall?: number | null;
  selectedKey?: string | null;
  onSelect?: (s: ToolStep) => void;
  testId?: string;
  emptyText?: string;
}) {
  const shown = limit ?? steps.length;
  const catchingUp = shown < steps.length;
  const [unfold, setUnfold] = useState<Set<string>>(new Set());
  const visible = steps.slice(0, shown);
  const beats = useMemo(
    () => buildBeats(visible, { fold: !running && !catchingUp, unfold }),
    [visible, running, catchingUp, unfold],
  );
  // Instant (scripted) runs would show 00:00.0 everywhere: only show clocks that say something.
  const clocks = steps.some((s) => (s.tMs ?? 0) >= 100);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Follow the newest waypoint while the run is being recorded.
    if ((running || catchingUp) && scroller.current) {
      scroller.current.scrollTo({ left: scroller.current.scrollWidth, behavior: "smooth" });
    }
  }, [beats.length, running, catchingUp]);

  const toggle = (headKey: string) =>
    setUnfold((prev) => {
      const next = new Set(prev);
      if (next.has(headKey)) next.delete(headKey);
      else next.add(headKey);
      return next;
    });

  if (!steps.length && !running) return <p className="px-2 py-8 text-fg-2">{emptyText}</p>;

  return (
    <div ref={scroller} className="path-scroll overflow-x-auto" data-testid={testId}
      data-complete={!running && !catchingUp ? "true" : "false"} aria-label="Flight path: the steps of this run, left to right">
      <ol className="flex min-w-max items-start px-1 pb-3 pt-1">
        {beats.map((b, i) => {
          const prev = i > 0 ? toneOf(beats[i - 1]) : null;
          const last = i === beats.length - 1 && !(running || catchingUp);
          return (
            <Column key={b.key} width={WIDTH[b.kind]} prevTone={prev} tone={toneOf(b)} last={last} animate={running || catchingUp}
              node={<Node beat={b} root={b.kind === "step" && b.key === rootKey} />}>
              {b.kind === "step" && (
                <WaypointCard step={b.step} mode={mode} root={b.key === rootKey} clock={clocks}
                  highlighted={highlightCall !== undefined && highlightCall === b.step.callIndex}
                  selected={selectedKey === b.key} onSelect={onSelect}
                  foldable={unfold.has(b.key)} onFold={() => toggle(b.key)} />
              )}
              {b.kind === "loop" && <LoopCard beat={b} onExpand={() => toggle(b.head.key)} />}
              {b.kind === "end" && <EndCard step={b.step} clock={clocks} />}
            </Column>
          );
        })}
        {(running || catchingUp) && (
          <Column width="w-[200px]" prevTone={beats.length ? toneOf(beats[beats.length - 1]) : null} tone="muted" last
            node={<span className="rec-dot h-3.5 w-3.5 rounded-full bg-ai ring-4 ring-ai-tint" />}>
            <div data-testid="tape-pending" className="mr-3 rounded-[12px] border border-dashed border-ai/40 bg-ai-tint/50 p-3 text-[14px] text-ai">
              {catchingUp ? "Replaying the recording…" : "Thinking about the next step…"}
            </div>
          </Column>
        )}
      </ol>
    </div>
  );
}

function Column({ width, prevTone, tone, last, node, children, animate }: {
  width: string; prevTone: Tone | null; tone: Tone; last: boolean; node: ReactNode; children: ReactNode; animate?: boolean;
}) {
  return (
    <li className={`relative shrink-0 ${width} ${animate ? "land" : ""}`}>
      <div className="relative flex h-10 items-center">
        {prevTone && <span aria-hidden className={`absolute left-0 top-1/2 w-6 -translate-y-1/2 border-t-2 ${TRACK[prevTone]}`} />}
        {!last && <span aria-hidden className={`absolute left-6 right-0 top-1/2 -translate-y-1/2 border-t-2 ${TRACK[tone]}`} />}
        <span className="relative z-10 ml-6 flex -translate-x-1/2 items-center justify-center">{node}</span>
      </div>
      {children}
    </li>
  );
}

function Node({ beat, root }: { beat: Beat; root: boolean }) {
  if (beat.kind === "loop") {
    return (
      <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-bad text-white">
        {/* holding pattern */}
        <svg aria-hidden viewBox="0 0 64 26" className="absolute h-[26px] w-16 text-bad/50">
          <ellipse cx="32" cy="13" rx="30" ry="11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="3 3" />
        </svg>
        <Icon name="loop" className="relative h-4 w-4" />
      </span>
    );
  }
  const tone = toneOf(beat);
  if (beat.kind === "end") {
    const bg = { ok: "bg-ok", bad: "bg-bad", warn: "bg-warn", muted: "bg-fg-2" }[tone];
    return <span className={`h-4 w-4 rounded-[4px] ${bg}`} />;
  }
  if (root) {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-bad text-white ring-[5px] ring-bad/20">
        <Icon name="x" className="h-4 w-4" />
      </span>
    );
  }
  const cls = {
    ok: "bg-surface text-ok ring-ok",
    bad: "bg-surface text-bad ring-bad",
    warn: "bg-surface text-warn ring-warn",
    muted: "bg-surface text-fg-2 ring-fg-3",
  }[tone];
  return (
    <span className={`flex h-5 w-5 items-center justify-center rounded-full ring-2 ${cls}`}>
      <Icon name={tone === "ok" ? "check" : tone === "warn" ? "clock" : tone === "bad" ? "x" : "check"} className="h-3 w-3" />
    </span>
  );
}

function WaypointCard({ step, mode, root, clock, highlighted, selected, onSelect, foldable, onFold }: {
  step: ToolStep; mode: ViewMode; root: boolean; clock: boolean; highlighted: boolean; selected: boolean;
  onSelect?: (s: ToolStep) => void; foldable: boolean; onFold: () => void;
}) {
  const view = describeStep(step);
  const technical = mode === "technical";
  const border = selected
    ? "border-fg shadow-[0_6px_18px_-8px_rgba(21,26,36,.35)]"
    : root
      ? "border-bad/50"
      : highlighted
        ? "border-context/60"
        : "border-line hover:border-line-strong";
  const body = (
    <>
      <div className="flex items-center justify-between text-[12.5px] text-fg-3">
        <span>Step {step.callIndex + 1}</span>
        {clock && step.tMs !== null && <span className="num">{fmtClock(step.tMs)}</span>}
      </div>
      {(root || step.intervention) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {root && <Pill tone="bad"><Icon name="flag" className="h-3 w-3" />Root cause</Pill>}
          {step.intervention && <Pill tone="context">Your change</Pill>}
        </div>
      )}
      <p className="mt-1 line-clamp-2 font-medium leading-snug">{stepTitle(step)}</p>
      {view.detail && <p className={`mt-1 line-clamp-3 text-[13.5px] leading-[19px] ${TEXT[view.tone]}`}>{view.detail}</p>}
      {step.note && (
        <p className="mt-2 line-clamp-2 text-[13px] leading-[18px] text-ai">
          <span className="font-medium">Thinking:</span> {step.note}
        </p>
      )}
      {technical && (
        <div className="mt-2 space-y-1">
          <div className="flex flex-wrap gap-1">
            <Tag tone="muted">{step.tool}</Tag>
            {step.errorCode && <Tag>{step.errorCode}</Tag>}
            {step.tokens !== null && <Pill tone="ai">{step.tokens} tokens</Pill>}
          </div>
          <p className="line-clamp-2 break-all font-mono text-[11.5px] leading-4 text-fg-2">{JSON.stringify(step.args)}</p>
        </div>
      )}
    </>
  );
  return (
    <div className="mr-3 mt-1" data-testid="tape-step" data-tone={view.tone} data-error={step.errorCode ?? ""} data-root={root ? "true" : undefined}>
      {onSelect ? (
        <button type="button" onClick={() => onSelect(step)} aria-pressed={selected}
          className={`block w-full rounded-[12px] border bg-surface p-3 text-left ${border} ${highlighted ? "bg-context-tint/40" : ""}`}>
          {body}
        </button>
      ) : (
        <div className={`rounded-[12px] border bg-surface p-3 ${border}`}>{body}</div>
      )}
      {foldable && (
        <button type="button" onClick={onFold} className={`${BTN_QUIET} mt-1`}>Fold the repeats</button>
      )}
    </div>
  );
}

function LoopCard({ beat, onExpand }: { beat: Extract<Beat, { kind: "loop" }>; onExpand: () => void }) {
  const n = beat.repeats.length;
  const first = beat.repeats[0].callIndex + 1;
  const last = beat.repeats[n - 1].callIndex + 1;
  return (
    <div className="relative mr-3 mt-1" data-testid="repeat-group">
      <span aria-hidden className="absolute inset-0 translate-x-2 translate-y-2 rounded-[12px] border border-bad/20 bg-surface" />
      <span aria-hidden className="absolute inset-0 translate-x-1 translate-y-1 rounded-[12px] border border-bad/30 bg-surface" />
      <div className="relative rounded-[12px] border border-bad/50 bg-surface p-3">
        <div className="flex items-center justify-between text-[12.5px] text-fg-3">
          <span>Steps {first}–{last}</span>
          <Pill tone="bad"><span className="num">×{n}</span></Pill>
        </div>
        <p className="mt-1 font-semibold text-bad">Stuck in a loop</p>
        <p className="mt-1 text-[13.5px] leading-[19px] text-fg-2">
          Repeated step {beat.head.callIndex + 1} exactly, {n} more times. Rejected every time; nothing changed between tries.
        </p>
        <button type="button" onClick={onExpand} className={`${BTN_QUIET} mt-2 -ml-1.5`}>Show all {n}</button>
      </div>
    </div>
  );
}

function EndCard({ step, clock }: { step: Extract<TapeStep, { kind: "finish" | "budget" }>; clock: boolean }) {
  const view = describeStep(step);
  return (
    <div className="mr-3 mt-1 rounded-[12px] border border-line bg-surface p-3" data-testid="tape-step" data-tone={view.tone}>
      <div className="flex items-center justify-between text-[12.5px] text-fg-3">
        <span>End of run</span>
        {clock && step.tMs !== null && <span className="num">{fmtClock(step.tMs)}</span>}
      </div>
      <p className={`mt-1 font-medium leading-snug ${view.tone === "bad" ? "text-bad" : ""}`}>{view.title}</p>
      {view.detail && <p className="mt-1 line-clamp-3 text-[13.5px] leading-[19px] text-fg-2">{view.detail}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ step detail
function fields(obj: Record<string, unknown> | null): [string, string][] {
  if (!obj) return [];
  return Object.entries(obj).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]);
}

function FieldList({ rows }: { rows: [string, string][] }) {
  if (!rows.length) return <p className="text-[13.5px] text-fg-3">Nothing recorded.</p>;
  return (
    <dl className="space-y-1 text-[13.5px]">
      {rows.slice(0, 6).map(([k, v]) => (
        <div key={k} className="grid grid-cols-[minmax(0,110px)_minmax(0,1fr)] gap-2">
          <dt className="truncate text-fg-2">{k.replaceAll("_", " ")}</dt>
          <dd className="line-clamp-3 break-words font-mono text-[12px] leading-[18px]">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** What the agent thought, sent and got back for one waypoint, side by side. */
export function StepDetail({ step, mode, onInspect }: { step: ToolStep; mode: ViewMode; onInspect?: (spanId: string) => void }) {
  const view = describeStep(step);
  const back = step.ok ? step.result : { error: step.errorCode, message: step.error };
  return (
    <section className="rounded-[12px] border border-line bg-surface p-4" data-testid="step-detail" aria-live="polite">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-[15px] font-semibold">Step {step.callIndex + 1}: {stepTitle(step)}</h3>
        {mode === "technical" && <Tag tone="muted">{step.tool}</Tag>}
        {mode === "technical" && step.spanId && <span className="font-mono text-[11.5px] text-fg-3">span {step.spanId}</span>}
        {onInspect && step.spanId && (
          <button type="button" className={`${BTN_QUIET} ml-auto`} onClick={() => onInspect(step.spanId as string)}>
            Open in technical trace
          </button>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-[10px] bg-ai-tint/70 p-3">
          <p className="text-[13px] font-medium text-ai">What the AI was thinking</p>
          <p className="mt-1 text-[14px] leading-5 text-fg">
            {step.note ?? <span className="text-fg-2">No reasoning recorded. The scripted agent follows a fixed plan.</span>}
          </p>
          {step.tokens !== null && <p className="mt-2 text-[12.5px] text-ai">{step.tokens} tokens for this decision</p>}
        </div>
        <div className="rounded-[10px] bg-context-tint/70 p-3">
          <p className="mb-1.5 text-[13px] font-medium text-context">What it sent to the {toolNoun(step.tool)}</p>
          <FieldList rows={fields(step.args)} />
        </div>
        <div className={`rounded-[10px] p-3 ${step.ok ? "bg-ok-tint/70" : view.tone === "warn" ? "bg-warn-tint/70" : "bg-bad-tint/70"}`}>
          <p className={`text-[13px] font-medium ${TEXT[view.tone]}`}>What came back</p>
          {view.detail && <p className="mt-1 text-[14px] leading-5">{view.detail}</p>}
          {!step.ok && step.error && mode === "technical" && <p className="mt-1 break-words font-mono text-[12px] text-fg-2">{step.error}</p>}
          {step.ok && <div className="mt-1.5"><FieldList rows={fields(step.result)} /></div>}
        </div>
      </div>
      <div className="mt-3">
        <Disclosure label="Show raw data">
          <div className="grid gap-2 md:grid-cols-2">
            <div><p className="mb-1 text-[12.5px] text-fg-2">Sent</p><JsonBlock value={step.args} max="max-h-48" /></div>
            <div><p className="mb-1 text-[12.5px] text-fg-2">Got back</p><JsonBlock value={back} max="max-h-48" /></div>
          </div>
        </Disclosure>
      </div>
    </section>
  );
}
