"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ExecutionDetail,
  type Finding,
  type Graph,
  type LiveConfig,
  liveApi,
  type ReplayJob,
  replayApi,
  type SuggestedFix,
  type Timeline,
} from "@/lib/api";
import { agentLabel, findingPlain, findingTitle, verdict } from "@/lib/describe";
import { fmtDuration, fmtTime, href, shortId } from "@/lib/format";
import { fromTimeline } from "@/lib/steps";
import { narrate, rootCause, stepNumberBySpan, type ToolStep } from "@/lib/story";
import { useApi } from "@/lib/use-api";
import { useViewMode, type ViewMode } from "@/lib/view-mode";
import { AnswerRow, NextStepCard } from "./answers";
import { FlightPath, StepDetail } from "./flight-path";
import { SummaryStrip } from "./summary-strip";
import { TraceTab } from "./trace";
import { BTN_SECONDARY, Card, ErrorBox, Icon, Loading, Pill, Segmented, StatusBadge, Tabs, Tag } from "./ui";

type TabId = "story" | "replay" | "trace" | "evidence";
const TAB_IDS: TabId[] = ["story", "replay", "trace", "evidence"];

type Loaded = {
  detail: ExecutionDetail;
  timeline: Timeline;
  graph: Graph;
  findings: Finding[];
  replays: ReplayJob[];
  cfg: LiveConfig | null;
  fix: SuggestedFix | null;
};

async function loadAll(id: string): Promise<Loaded> {
  const [detail, timeline, graph, findings, replays, cfg] = await Promise.all([
    api.execution(id),
    api.timeline(id),
    api.graph(id),
    replayApi.findings(id),
    replayApi.replaysOf(id),
    liveApi.config().catch(() => null),
  ]);
  const fix = detail.status === "failed" && !detail.parent_execution_id
    ? await liveApi.suggestedFix(id).catch(() => null)
    : null;
  return { detail, timeline, graph, findings: findings.findings, replays, cfg, fix };
}

function readTab(): TabId {
  if (typeof window === "undefined") return "story";
  const t = new URLSearchParams(window.location.search).get("tab");
  return TAB_IDS.includes(t as TabId) ? (t as TabId) : "story";
}

export function RunView({ id }: { id: string }) {
  const { data, error, loading, reload } = useApi(() => loadAll(id), id);
  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-5 sm:px-6">
      <p className="mb-3">
        <a href={href("/runs")} className="inline-flex items-center gap-1 text-[14px] text-fg-2 hover:text-fg">
          <Icon name="arrow" className="h-3.5 w-3.5 rotate-180" />Runs
        </a>
      </p>
      {loading && !data && <Card><Loading label="Loading the recording…" /></Card>}
      {error && <Card><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Loaded data={data} />}
    </main>
  );
}

function Loaded({ data }: { data: Loaded }) {
  const { detail, timeline, graph, findings, replays, cfg, fix } = data;
  const [mode, setMode] = useViewMode();
  const [tab, setTabState] = useState<TabId>("story");
  useEffect(() => setTabState(readTab()), []);
  const setTab = (t: TabId) => {
    setTabState(t);
    const q = new URLSearchParams(window.location.search);
    if (t === "story") q.delete("tab");
    else q.set("tab", t);
    window.history.replaceState(null, "", `${window.location.pathname}${q.size ? `?${q}` : ""}`);
  };

  const a = detail.attributes as Record<string, unknown>;
  const verifier = a.verifier as { passed?: boolean; reasons?: string[] } | undefined;
  const usage = a.usage as { total_tokens?: number } | undefined;
  const scenario = cfg?.scenarios.find((s) => s.fixture_id === detail.task_id);
  const steps = useMemo(() => fromTimeline(timeline.events), [timeline]);
  const tools = steps.filter((s): s is ToolStep => s.kind === "tool");
  const passed = verifier?.passed ?? detail.status === "succeeded";
  const v = verdict({ passed, termination: detail.termination, reasons: verifier?.reasons, categories: findings.map((f) => f.category) });
  const cause = rootCause(findings, steps, { passed, reasons: verifier?.reasons, termination: detail.termination });
  const summary = narrate(steps, { passed, termination: detail.termination, fallback: v.line }, cause);
  const budget = steps.find((s) => s.kind === "budget") as { max: number | null } | undefined;
  const isFork = Boolean(detail.parent_execution_id);
  const replayInfo = a.replay as { job_id?: string; checkpoint_step_index?: number } | undefined;

  const firstFailing = tools.find((s) => !s.ok);
  const [selectedKey, setSelectedKey] = useState<string | null>(cause?.step?.key ?? firstFailing?.key ?? tools[0]?.key ?? null);
  const selected = tools.find((s) => s.key === selectedKey) ?? null;
  const [span, setSpan] = useState<string | null>(cause?.step?.spanId ?? graph.nodes.find((n) => n.parent_span_id === null)?.id ?? null);
  const [fixTarget, setFixTarget] = useState<number | null>(null);
  const onFixTarget = useCallback((c: number | null) => setFixTarget(c), []);

  const jumpToStep = (key: string) => {
    setTab("story");
    setSelectedKey(key);
    setTimeout(() => document.getElementById("step-detail")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 30);
  };
  const inspect = (spanId: string) => {
    setSpan(spanId);
    setTab("trace");
  };

  const action = passed
    ? null
    : fix && fix.available
      ? { label: fix.label, onClick: () => { setTab("story"); setTimeout(() => document.getElementById("try-next")?.scrollIntoView({ behavior: "smooth", block: "center" }), 30); } }
      : { label: "Test a change in Replay Studio", href: href(`/runs/${detail.id}/replay`) };

  return (
    <>
      <header className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-[30px] font-semibold leading-9 tracking-tight" data-testid="run-title">
          {scenario?.title ?? detail.task_id.replaceAll("_", " ")}
        </h1>
        <StatusBadge status={detail.status} size="lg" />
        {isFork && <Pill tone="context">Re-run</Pill>}
        <div className="ml-auto flex items-center gap-2">
          <div className="sm:hidden">
            <Segmented label="Detail level" value={mode} onChange={setMode}
              options={[{ id: "simple", label: "Simple" }, { id: "technical", label: "Technical" }]} />
          </div>
          <a href={href(`/runs/${detail.id}/replay`)} data-testid="open-replay-studio" className={BTN_SECONDARY}>
            Open Replay Studio
          </a>
        </div>
        <p className="basis-full text-[14px] text-fg-2">
          Recorded {fmtTime(detail.started_at)}
          {mode === "technical" && <span className="ml-3 font-mono text-[12.5px]" title={detail.id}>run {shortId(detail.id)}</span>}
          {isFork && (
            <span className="ml-3">
              Restarted before step {(replayInfo?.checkpoint_step_index ?? 0) + 1} of the{" "}
              <a className="underline underline-offset-4" href={href(`/runs/${detail.parent_execution_id}`)}>original run</a>
              {replayInfo?.job_id && <> (<a className="underline underline-offset-4" href={href(`/replays/${replayInfo.job_id}`)}>compare</a>)</>}
            </span>
          )}
        </p>
      </header>

      <SummaryStrip d={{
        status: detail.status,
        situation: scenario?.title ?? detail.task_id.replaceAll("_", " "),
        agent: agentLabel(detail.agent_version.model_name, cfg?.llm_label),
        steps: detail.tool_calls,
        stepLimit: budget?.max ?? null,
        duration: fmtDuration(detail.duration_ms),
        tokens: usage?.total_tokens ?? null,
        rootCause: cause ? cause.title : null,
        passed,
        action,
      }} />

      <div className="mt-5">
        <Tabs label="Run views" value={tab} onChange={setTab} tabs={[
          { id: "story", label: "Story" },
          { id: "replay", label: "Replay", count: replays.length },
          { id: "trace", label: "Technical trace" },
          { id: "evidence", label: "Evidence", count: findings.length },
        ]} />
      </div>

      <div className="mt-4" role="tabpanel">
        {tab === "story" && (
          <div className="space-y-4">
            <div id="try-next">
              <AnswerRow summary={summary} passed={passed} cause={cause} mode={mode} executionId={detail.id}
                canFix={!isFork} onJumpToStep={jumpToStep} onFixTarget={onFixTarget}
                failedSteps={detail.tool_calls} expected={!passed ? scenario?.expected : null} />
            </div>
            <section className="rounded-[16px] border border-line bg-surface px-4 pb-1 pt-3">
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <h2 className="text-[15px] font-semibold">Flight path</h2>
                <p className="hidden text-[13px] text-fg-3 sm:block">Click a step to see what the agent thought, sent and got back.</p>
              </div>
              <FlightPath steps={steps} mode={mode} rootKey={passed ? null : cause?.step?.key}
                highlightCall={fixTarget} selectedKey={selectedKey} onSelect={(s) => setSelectedKey(s.key)} />
            </section>
            <div id="step-detail">
              {selected && <StepDetail step={selected} mode={mode} onInspect={inspect} />}
            </div>
          </div>
        )}

        {tab === "replay" && (
          <ReplayTab detail={detail} replays={replays} mode={mode} isFork={isFork} replayJob={replayInfo?.job_id ?? null} failed={!passed} />
        )}

        {tab === "trace" && (
          <TraceTab timeline={timeline} graph={graph} findings={findings} selected={span} onSelect={setSpan} />
        )}

        {tab === "evidence" && (
          <EvidenceTab findings={findings} causeId={cause?.finding?.id ?? null} mode={mode}
            spanToStep={stepNumberBySpan(steps)} steps={tools} onJump={jumpToStep} onInspect={inspect} />
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ replay tab
function ReplayTab({ detail, replays, mode, isFork, replayJob, failed }: {
  detail: ExecutionDetail; replays: ReplayJob[]; mode: ViewMode; isFork: boolean; replayJob: string | null; failed: boolean;
}) {
  if (isFork) {
    return (
      <Card>
        <div className="p-5">
          <p className="text-[17px] font-semibold">This run is itself a re-run.</p>
          <p className="mt-1 text-fg-2">It restarted the original from a saved step with one change.</p>
          <div className="mt-3 flex gap-2">
            {replayJob && <a className={BTN_SECONDARY} href={href(`/replays/${replayJob}`)}>Compare with the original</a>}
            <a className={BTN_SECONDARY} href={href(`/runs/${detail.parent_execution_id}`)}>Open the original</a>
          </div>
        </div>
      </Card>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        {failed ? (
          <NextStepCard executionId={detail.id} failedBefore={detail.tool_calls} wide mode={mode} />
        ) : (
          <Card><p className="p-5 text-fg-2">This run passed, so there is no suggested fix. You can still test how it reacts to a change in Replay Studio.</p></Card>
        )}
      </div>
      <div className="space-y-4">
        <Card title="Re-runs of this run" aside={<span className="num text-[13px] text-fg-3">{replays.length}</span>}>
          {replays.length === 0 ? (
            <p className="px-4 py-4 text-[14px] text-fg-2">None yet. A re-run restarts this run from a saved step with one change; this run is never edited.</p>
          ) : (
            <ul className="divide-y divide-line">
              {replays.map((r) => {
                const ok = r.result.fork_verifier_passed === true;
                return (
                  <li key={r.job_id}>
                    <a href={href(`/replays/${r.job_id}`)} className="flex items-center gap-3 px-4 py-3 hover:bg-canvas">
                      <span className="text-[14px]">From step {r.checkpoint_step_index + 1}</span>
                      <span className="ml-auto flex items-center gap-1.5">
                        <StatusBadge status="failed" />
                        <Icon name="arrow" className="h-3.5 w-3.5 text-fg-3" />
                        <StatusBadge status={r.status !== "succeeded" ? r.status : ok ? "succeeded" : "failed"} />
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <Card>
          <div className="p-4">
            <p className="font-semibold">Design your own change</p>
            <p className="mt-1 text-[14px] text-fg-2">Pick any step, change what the agent sent or what a tool answered, and watch the rest of the run again.</p>
            <a href={href(`/runs/${detail.id}/replay`)} className={`${BTN_SECONDARY} mt-3`}>Open Replay Studio</a>
          </div>
        </Card>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ evidence tab
function EvidenceTab({ findings, causeId, mode, spanToStep, steps, onJump, onInspect }: {
  findings: Finding[]; causeId: string | null; mode: ViewMode; spanToStep: Map<string, number>; steps: ToolStep[];
  onJump: (key: string) => void; onInspect: (span: string) => void;
}) {
  if (!findings.length) {
    return (
      <Card>
        <p className="p-5 text-fg-2" data-testid="no-findings">None of the automatic checks matched this run. The flight path in the Story tab shows everything the agent did.</p>
      </Card>
    );
  }
  const ordered = [...findings].sort((x, y) => (x.id === causeId ? -1 : y.id === causeId ? 1 : 0));
  return (
    <div className="space-y-3" data-testid="findings">
      <p className="text-[13.5px] text-fg-2">
        Found by rule-based checks on the recording. Each one cites the steps it is based on. They describe what happened, not a proven cause.
      </p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {ordered.map((f) => {
          const isCause = f.id === causeId;
          const nums = [...new Set(f.evidence_span_ids.map((s) => spanToStep.get(s)).filter((n): n is number => n !== undefined))].sort((x, y) => x - y);
          return (
            <article key={f.id} data-testid="finding" data-category={f.category}
              className={`rounded-[12px] border bg-surface p-4 ${isCause ? "border-bad/45" : "border-line"}`}>
              <div className="flex items-center gap-2">
                <Pill tone={isCause ? "bad" : "neutral"}>{isCause ? "Most likely cause" : "Symptom"}</Pill>
                <span className="ml-auto text-[12.5px] text-fg-3">{f.severity} severity</span>
              </div>
              <p className="mt-2 font-semibold leading-snug">{findingTitle(f)}</p>
              <p className="mt-1 text-[14px] leading-5 text-fg-2">{findingPlain(f)}</p>
              {nums.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <span className="text-[12.5px] text-fg-2">Evidence</span>
                  {nums.slice(0, 8).map((n) => {
                    const st = steps.find((s) => s.callIndex + 1 === n);
                    return (
                      <button key={n} type="button" onClick={() => st && onJump(st.key)}
                        className="num rounded-full border border-line-strong px-2 text-[12.5px] hover:border-fg-3">step {n}</button>
                    );
                  })}
                  {nums.length > 8 && <span className="text-[12.5px] text-fg-3">+{nums.length - 8} more</span>}
                </div>
              )}
              {mode === "technical" ? (
                <div className="mt-3 space-y-1.5 border-t border-line pt-3 text-[12.5px]">
                  <p className="break-words font-mono text-[11.5px] leading-[17px] text-fg-2">{f.explanation}</p>
                  <div className="flex flex-wrap gap-1"><Tag tone="muted">{f.category}</Tag><Tag tone="muted">{f.detector} v{f.detector_version}</Tag><Tag tone="muted">{f.kind}</Tag></div>
                  {f.caveats.length > 0 && <ul className="list-inside list-disc text-fg-2">{f.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
                  {f.evidence_span_ids[0] && (
                    <button type="button" className="text-fg-2 underline underline-offset-4" onClick={() => onInspect(f.evidence_span_ids[0])}>Open the first cited span in the trace</button>
                  )}
                </div>
              ) : (
                <details className="mt-2 text-[13px] text-fg-2">
                  <summary className="cursor-pointer underline decoration-line-strong underline-offset-4">Technical details</summary>
                  <p className="mt-1 break-words font-mono text-[11.5px] leading-[17px]">{f.explanation}</p>
                </details>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
