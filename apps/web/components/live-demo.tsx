"use client";

import { SHOWCASE } from "@/lib/showcase";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import {
  type Brain,
  type Finding,
  type LiveConfig,
  type LiveRun,
  type LiveStep,
  liveApi,
  replayApi,
  type Scenario,
} from "@/lib/api";
import { fmtClock, verdict } from "@/lib/describe";
import { href } from "@/lib/format";
import { fromLive } from "@/lib/steps";
import { narrate, rootCause, type ToolStep } from "@/lib/story";
import { useApi } from "@/lib/use-api";
import { useViewMode } from "@/lib/view-mode";
import { AnswerRow } from "./answers";
import { FlightPath, StepDetail, usePacedCount } from "./flight-path";
import { BTN_PRIMARY, ErrorBox, Loading } from "./ui";

type Run = {
  liveId: string;
  brain: Brain;
  scenario: Scenario;
  status: LiveRun["status"];
  steps: LiveStep[];
  executionId: string | null;
  error: string | null;
  startedAt: number;
  endedAt: number | null;
};

const HOW = [
  ["Hand over a ticket", "A support agent gets a customer's request and works it with real tools: orders, stock, policy."],
  ["Every step is recorded", "Each step lands on the flight path as it happens: what the AI thought, sent and got back."],
  ["See what broke, test a fix", "If it fails, FlightPath names the most likely cause and re-runs from that step with one change."],
] as const;

export function LiveDemo() {
  const cfg = useApi(() => liveApi.config(), "live-config");
  // A model running on this machine takes a minute or two to load: check back until ready.
  const llmState = cfg.data?.llm_state;
  const { reload } = cfg;
  useEffect(() => {
    if (llmState !== "loading") return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [llmState, reload]);
  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 sm:px-6">
      <header className="grid gap-6 pb-6 pt-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:items-end">
        <div>
          <h1 className="text-[36px] font-semibold leading-[42px] tracking-tight sm:text-[42px] sm:leading-[48px]">
            Watch an AI agent work. See exactly where it goes wrong.
          </h1>
          <p className="mt-3 max-w-xl text-[16.5px] leading-7 text-fg-2">
            FlightPath is the flight recorder for AI agents. Give a support agent a ticket and follow the run step by step.
          </p>
        </div>
        <ol className="grid gap-px overflow-hidden rounded-[12px] border border-line bg-line sm:grid-cols-3" data-testid="how-it-works">
          {HOW.map(([t, d], i) => (
            <li key={t} className="bg-surface px-4 py-3">
              <p className="flex items-center gap-2 font-semibold">
                <span className="num flex h-5 w-5 items-center justify-center rounded-full bg-fg text-[12px] text-white">{i + 1}</span>
                {t}
              </p>
              <p className="mt-1 text-[13.5px] leading-5 text-fg-2">{d}</p>
            </li>
          ))}
        </ol>
      </header>
      {cfg.loading && !cfg.data && <Loading label="Starting up…" />}
      {cfg.error && <ErrorBox message={cfg.error} onRetry={cfg.reload} />}
      {cfg.data && <Demo cfg={cfg.data} />}
    </main>
  );
}

function Demo({ cfg }: { cfg: LiveConfig }) {
  const [brain, setBrain] = useState<Brain>(cfg.llm_available ? "llm" : "scripted");
  const brainTouched = useRef(false);
  const pickBrain = (b: Brain) => {
    brainTouched.current = true;
    setBrain(b);
  };
  useEffect(() => {
    // The model finished loading while the page was open: offer it, unless the visitor chose.
    if (cfg.llm_available && !brainTouched.current) setBrain("llm");
    if (!cfg.llm_available && brain === "llm") setBrain("scripted");
  }, [cfg.llm_available, brain]);
  const usable = cfg.scenarios.filter((s) => s.brains.includes(brain));
  const [scenarioId, setScenarioId] = useState(cfg.scenarios[0]?.id ?? "");
  const scenario = usable.find((s) => s.id === scenarioId) ?? usable[0];
  const [message, setMessage] = useState(scenario?.default_message ?? "");
  const [run, setRun] = useState<Run | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = starting || (run !== null && (run.status === "queued" || run.status === "running"));

  useEffect(() => {
    if (scenario) setMessage(scenario.default_message);
  }, [scenario]);

  async function start() {
    if (!scenario) return;
    setStarting(true);
    setStartError(null);
    try {
      const { data } = await liveApi.start({ scenario: scenario.id, brain, message: brain === "llm" ? message : undefined });
      setRun({
        liveId: data.live_id, brain, scenario, status: data.status, steps: data.steps,
        executionId: data.execution_id, error: data.error, startedAt: Date.now(), endedAt: null,
      });
      document.getElementById("stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setStartError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  // Follow the run until it ends.
  const liveId = run?.liveId;
  useEffect(() => {
    if (!liveId) return;
    let alive = true;
    let next = 0;
    const tick = async () => {
      while (alive) {
        try {
          const r = await liveApi.poll(liveId, next);
          if (!alive) return;
          next = r.next;
          setRun((prev) =>
            prev && prev.liveId === liveId
              ? {
                  ...prev,
                  status: r.status,
                  steps: [...prev.steps.slice(0, next - r.steps.length), ...r.steps],
                  executionId: r.execution_id,
                  error: r.error,
                  endedAt: r.status === "done" || r.status === "error" ? Date.now() : null,
                }
              : prev,
          );
          if (r.status === "done" || r.status === "error") return;
        } catch {
          /* transient: keep polling */
        }
        await new Promise((res) => setTimeout(res, 600));
      }
    };
    void tick();
    return () => {
      alive = false;
    };
  }, [liveId]);

  const llmSub = {
    ready: cfg.llm_label,
    loading: "Warming up, about a minute…",
    offline: "AI server is not running",
    none: SHOWCASE ? "Runs when you host FlightPath yourself" : "Not set up on this server",
  }[cfg.llm_state];

  return (
    <>
      <form
        className="rounded-[16px] border border-line bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          <fieldset>
            <legend className="text-[13.5px] font-medium text-fg-2">Agent</legend>
            <div className="mt-1.5 grid grid-cols-2 gap-2 xl:grid-cols-1" role="radiogroup">
              <BrainOption active={brain === "llm"} disabled={!cfg.llm_available} onPick={() => pickBrain("llm")}
                title="Live AI" sub={llmSub} tone="ai" />
              <BrainOption active={brain === "scripted"} onPick={() => pickBrain("scripted")}
                title="Scripted" sub="Same steps every time, failures on cue" tone="neutral" />
            </div>
          </fieldset>
          <fieldset className="min-w-0">
            <legend className="text-[13.5px] font-medium text-fg-2">Situation</legend>
            <div className="mt-1.5 grid grid-cols-2 gap-2 md:grid-cols-3 xl:[grid-template-columns:repeat(var(--n),minmax(0,1fr))]" style={{ "--n": usable.length } as CSSProperties}>
              {usable.map((s) => {
                const on = s.id === scenario?.id;
                return (
                  <label key={s.id}
                    className={`relative flex cursor-pointer flex-col rounded-[10px] border px-3 py-2.5 ${on ? "border-fg bg-surface shadow-[0_0_0_1px_var(--color-fg)]" : "border-line bg-canvas/60 hover:border-line-strong"}`}>
                    <input type="radio" name="scenario" className="sr-only" checked={on}
                      onChange={() => setScenarioId(s.id)} data-testid={`scenario-${s.id}`} />
                    <span className="font-medium leading-snug">{s.title}</span>
                    <span className="mt-0.5 line-clamp-2 text-[13px] leading-[18px] text-fg-2">{s.blurb}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        </div>
        <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 md:flex-row md:items-end">
          {brain === "llm" && scenario ? (
            <label className="block min-w-0 flex-1">
              <span className="text-[13.5px] font-medium text-fg-2">Customer&apos;s message</span>
              <input value={message} onChange={(e) => setMessage(e.target.value)} maxLength={cfg.message_max_chars}
                className="mt-1.5 block w-full rounded-[8px] border border-line-strong bg-surface px-3 py-2" />
              <span className="mt-1 block text-[12.5px] text-fg-3">Right outcome for this situation: {scenario.expected}.</span>
            </label>
          ) : (
            <p className="flex-1 text-[14px] text-fg-2">
              {scenario ? <>The right outcome for this situation: <span className="text-fg">{scenario.expected}</span>.</> : null}
            </p>
          )}
          <button type="submit" disabled={busy || !scenario} className={`${BTN_PRIMARY} px-6 py-2.5 text-[16px] md:min-w-[200px]`} data-testid="run-agent">
            {busy ? "In the air…" : "Start the run"}
          </button>
        </div>
        {startError && <p role="alert" className="mt-3 text-bad">{startError}</p>}
        {cfg.public_demo && brain === "llm" && (
          <p className="mt-2 text-[12.5px] text-fg-3">Public demo: AI runs are limited per hour. Messages you type are stored with the run.</p>
        )}
      </form>

      <section id="stage" className="mt-4 scroll-mt-20" aria-live="polite">
        {run ? <Recording key={run.liveId} run={run} /> : <EmptyStage />}
      </section>
    </>
  );
}

function BrainOption({ active, disabled, onPick, title, sub, tone }: {
  active: boolean; disabled?: boolean; onPick: () => void; title: string; sub: string; tone: "ai" | "neutral";
}) {
  return (
    <button type="button" role="radio" aria-checked={active} disabled={disabled} onClick={onPick}
      className={`rounded-[10px] border px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-50 ${active ? "border-fg shadow-[0_0_0_1px_var(--color-fg)]" : "border-line bg-canvas/60 hover:border-line-strong"}`}>
      <span className="flex items-center gap-1.5 font-medium">
        <span aria-hidden className={`h-2 w-2 rounded-full ${tone === "ai" ? "bg-ai" : "bg-fg-3"}`} />
        {title}
      </span>
      <span className="block truncate text-[12.5px] text-fg-2">{sub}</span>
    </button>
  );
}

function EmptyStage() {
  return (
    <div className="rounded-[16px] border border-dashed border-line-strong bg-surface/60 px-6 py-8">
      <div aria-hidden className="flex items-center">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex flex-1 items-center last:flex-none">
            <span className="h-4 w-4 rounded-full border-2 border-line-strong bg-surface" />
            {i < 4 && <span className="h-0 flex-1 border-t-2 border-dashed border-line-strong" />}
          </div>
        ))}
      </div>
      <p className="mt-5 text-[17px] font-semibold">The flight path is empty</p>
      <p className="mt-1 max-w-xl text-fg-2">Pick an agent and a situation, then start the run. Each step lands here as it happens.</p>
    </div>
  );
}

function Recording({ run }: { run: Run }) {
  const [mode] = useViewMode();
  const steps = fromLive(run.steps);
  const finished = run.status === "done" || run.status === "error";
  // The scripted agent finishes in milliseconds; reveal its steps at a readable pace.
  const shown = usePacedCount(steps.length, run.brain === "scripted");
  const revealed = shown >= steps.length;
  const end = run.steps.find((s) => s.kind === "end");
  const [now, setNow] = useState(Date.now());
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [fixTarget, setFixTarget] = useState<number | null>(null);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [finished]);
  useEffect(() => {
    if (run.status === "done" && revealed && run.executionId && findings === null) {
      replayApi.findings(run.executionId).then((f) => setFindings(f.findings), () => setFindings([]));
    }
  }, [run.status, revealed, run.executionId, findings]);
  const elapsed = (run.endedAt ?? now) - run.startedAt;
  const recording = !finished || !revealed;
  const passed = end?.kind === "end" ? end.verifier_passed : null;
  const termination = end?.kind === "end" ? end.termination : null;
  const tools = steps.filter((s): s is ToolStep => s.kind === "tool");
  const selected = tools.find((s) => s.key === selectedKey) ?? null;
  const ready = run.status === "done" && revealed && run.executionId && findings !== null;
  const v = verdict({ passed, termination, categories: findings?.map((f) => f.category) });
  const cause = ready ? rootCause(findings ?? [], steps, { passed, termination }) : null;

  return (
    <div className="space-y-4">
      <div className="rounded-[16px] border border-line bg-surface" data-testid="recording" data-status={run.status}>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2.5">
          <span className="flex items-center gap-2 font-semibold">
            <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${recording ? "rec-dot bg-context" : passed ? "bg-ok" : "bg-fg-3"}`} />
            {recording ? "Recording" : "Recorded"}
          </span>
          <span className="num text-fg-2">{fmtClock(elapsed)}</span>
          <span className="text-fg-2">{run.scenario.title}</span>
          <span className={`text-[13px] ${run.brain === "llm" ? "text-ai" : "text-fg-3"}`}>{run.brain === "llm" ? "Live AI" : "Scripted agent"}</span>
          {run.executionId && revealed && (
            <a className="ml-auto text-[14px] font-medium underline underline-offset-4" href={href(`/runs/${run.executionId}`)} data-testid="open-run">
              Open the full run
            </a>
          )}
        </div>
        <div className="px-3 pt-2">
          <FlightPath steps={steps} mode={mode} running={!finished} limit={shown} highlightCall={fixTarget}
            rootKey={ready && passed === false ? cause?.step?.key : null}
            selectedKey={selectedKey} onSelect={(s) => setSelectedKey((k) => (k === s.key ? null : s.key))} />
        </div>
        {run.status === "error" && (
          <p role="alert" className="mx-4 mb-4 rounded-[8px] bg-bad-tint px-4 py-3 text-bad">{run.error ?? "The run stopped unexpectedly."}</p>
        )}
      </div>
      {selected && <StepDetail step={selected} mode={mode} />}
      {ready && run.executionId && (
        <AnswerRow
          summary={narrate(steps, { passed, termination, fallback: v.line }, cause)}
          passed={Boolean(passed)} cause={cause} mode={mode} executionId={run.executionId} canFix
          onFixTarget={setFixTarget} failedSteps={tools.length} expected={run.scenario.expected}
          onJumpToStep={(k) => setSelectedKey(k)} />
      )}
    </div>
  );
}
