"use client";

import { type ReactNode, useState } from "react";
import { api, type Comparison, type ComparisonSide, type Graph, replayApi, type StepSide } from "@/lib/api";
import { errorText, toolTitle } from "@/lib/describe";
import { fmtDuration, href, shortId } from "@/lib/format";
import { symptomLabel } from "@/lib/story";
import { useApi } from "@/lib/use-api";
import { useViewMode, type ViewMode } from "@/lib/view-mode";
import { ExecutionGraph } from "./execution-graph";
import { Card, ErrorBox, Icon, Loading, Pill, StatusBadge, Tag } from "./ui";

type Loaded = { cmp: Comparison; sourceGraph: Graph; forkGraph: Graph };

async function load(jobId: string): Promise<Loaded> {
  const cmp = await replayApi.comparison(jobId);
  const [sourceGraph, forkGraph] = await Promise.all([api.graph(cmp.source.execution_id), api.graph(cmp.fork.execution_id)]);
  return { cmp, sourceGraph, forkGraph };
}

export function ComparisonView({ jobId }: { jobId: string }) {
  const { data, error, loading, reload } = useApi(() => load(jobId), jobId);
  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-5 sm:px-6">
      {data && (
        <p className="mb-3">
          <a href={href(`/runs/${data.cmp.source.execution_id}`)} className="inline-flex items-center gap-1 text-[14px] text-fg-2 hover:text-fg">
            <Icon name="arrow" className="h-3.5 w-3.5 rotate-180" />Back to the original run
          </a>
        </p>
      )}
      {loading && !data && <Card className="mt-4"><Loading label="Loading the comparison…" /></Card>}
      {error && <Card className="mt-4"><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Body data={data} />}
    </main>
  );
}

function Body({ data }: { data: Loaded }) {
  const { cmp, sourceGraph, forkGraph } = data;
  const [mode] = useViewMode();
  const [srcSel, setSrcSel] = useState<string | null>(null);
  const [forkSel, setForkSel] = useState<string | null>(null);
  const [techOpen, setTechOpen] = useState(false);
  const intervenedFork = cmp.steps.filter((s) => s.intervened && s.fork?.span_id).map((s) => s.fork!.span_id as string);
  return (
    <div className="space-y-4" data-testid="comparison">
      <Headline cmp={cmp} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)_minmax(0,1fr)]">
        <Outcome title="Before" side={cmp.source} mode={mode} />
        <ChangeCard cmp={cmp} />
        <Outcome title="After the change" side={cmp.fork} mode={mode} testId="fork-outcome" rerun />
      </div>

      <AlignedPaths cmp={cmp} mode={mode} />

      <details className="rounded-[12px] border border-line bg-surface" data-testid="comparison-tech"
        onToggle={(e) => setTechOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer px-4 py-3 font-semibold">
          Technical details <span className="font-normal text-fg-2">sandbox changes and span graphs</span>
        </summary>
        {techOpen && (
          <div className="space-y-4 border-t border-line p-4">
            <Card title="What each run left behind in its sandbox">
              {cmp.state_diff === null ? (
                <p className="px-4 py-3 text-sm text-fg-2">{cmp.state_diff_note}</p>
              ) : cmp.state_diff.length === 0 ? (
                <p className="px-4 py-3 text-fg-2">Identical in both runs.</p>
              ) : (
                <table className="w-full text-sm" data-testid="state-diff">
                  <thead className="text-left text-xs text-fg-2"><tr><th className="px-4 py-2">Path</th><th className="px-2 py-2">Change</th><th className="px-2 py-2">Original</th><th className="px-4 py-2">Re-run</th></tr></thead>
                  <tbody className="divide-y divide-line">
                    {cmp.state_diff.map((d) => (
                      <tr key={d.path}>
                        <td className="px-4 py-2 font-mono text-xs">{d.path}</td>
                        <td className="px-2 py-2 text-xs">{d.change}</td>
                        <td className="px-2 py-2 font-mono text-xs text-bad">{d.source === null ? "none" : JSON.stringify(d.source)}</td>
                        <td className="px-4 py-2 font-mono text-xs text-ok">{d.fork === null ? "none" : JSON.stringify(d.fork)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title={`Before: span graph (${shortId(cmp.source.execution_id)})`}>
                <ExecutionGraph graph={sourceGraph} selected={srcSel} onSelect={setSrcSel} height="h-[440px]" testId="source-graph" />
              </Card>
              <Card title={`After: span graph, re-run steps only (${shortId(cmp.fork.execution_id)})`}>
                <ExecutionGraph graph={forkGraph} selected={forkSel} onSelect={setForkSel} intervenedSpans={intervenedFork} height="h-[440px]" testId="fork-graph" />
              </Card>
            </div>
          </div>
        )}
      </details>

      <p className="text-[12.5px] text-fg-3" data-testid="caveat">{cmp.caveat}</p>
    </div>
  );
}

function Headline({ cmp }: { cmp: Comparison }) {
  const before = cmp.source.verifier?.passed;
  const after = cmp.fork.verifier?.passed;
  const text = !before && after
    ? "Fixed by one change."
    : before && !after
      ? "The change broke a run that used to pass."
      : after
        ? "Both runs pass."
        : "Still failing after the change.";
  return (
    <div>
      <h1 className={`text-[30px] font-semibold leading-9 tracking-tight ${after ? "text-ok" : "text-bad"}`}>{text}</h1>
      <p className="mt-0.5 text-fg-2">
        Restarted before step {cmp.checkpoint.step_index + 1}
        {cmp.first_divergence_call_index !== null ? `. The two paths split at step ${cmp.first_divergence_call_index + 1}` : ""}.
        {cmp.replay_mode === "deterministic"
          ? " The scripted agent is exact, so this result repeats every time."
          : " The AI decided again after the change, so another re-run may differ."}
      </p>
    </div>
  );
}

const ENDED: Record<string, string> = {
  completed: "the agent finished",
  budget_exhausted: "it ran out of steps",
  tool_failure: "the agent gave up",
};

function Outcome({ title, side, testId, mode, rerun }: { title: string; side: ComparisonSide; testId?: string; mode: ViewMode; rerun?: boolean }) {
  const m = side.metrics;
  const ok = side.verifier?.passed;
  return (
    <section className={`rounded-[12px] border bg-surface p-4 ${ok ? "border-ok/40" : "border-bad/40"}`} data-testid={testId}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[13.5px] font-medium text-fg-2">{title}</h2>
        <a className="text-[13px] text-fg-2 underline underline-offset-4" href={href(`/runs/${side.execution_id}`)}>Open run</a>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <StatusBadge status={side.status} size="lg" />
      </div>
      <p className="mt-2 text-[14px]">
        Outcome check:{" "}
        <b className={ok ? "text-ok" : "text-bad"} data-testid="verifier">{ok ? "passed" : "failed"}</b>
        {side.termination && <span className="text-fg-2">, {ENDED[side.termination] ?? side.termination}</span>}
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-2">
        {([
          [rerun ? "Steps re-run" : "Steps", String(m.tool_calls_recorded ?? "–")],
          ["Errors", String(m.tool_errors ?? "–")],
          ["Time", fmtDuration(m.duration_ms)],
        ] as const).map(([k, v]) => (
          <div key={k}><dt className="text-[12.5px] text-fg-2">{k}</dt><dd className="num text-[20px] font-semibold">{v}</dd></div>
        ))}
      </dl>
      {mode === "technical" && (
        <p className="mt-1 text-[12.5px] text-fg-2">
          <span className="text-ai">{m.tokens ?? 0} tokens</span>, {m.llm_calls_recorded ?? 0} AI decisions
          <span className="ml-2 font-mono text-[11.5px] text-fg-3">{shortId(side.execution_id)}</span>
          {side.verifier?.reasons && side.verifier.reasons.length > 0 && <span className="mt-1 block font-mono text-[11.5px]">{side.verifier.reasons.join(", ")}</span>}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-1">
        {side.findings.length === 0
          ? <span className="text-[13px] text-fg-2">No problems found</span>
          : side.findings.map((f) => <Pill key={f.category + f.title} tone="bad">{symptomLabel(f.category)}</Pill>)}
      </div>
    </section>
  );
}

function ChangeCard({ cmp }: { cmp: Comparison }) {
  const iv = cmp.intervention;
  if (!iv) {
    return (
      <section className="rounded-[12px] border border-line bg-context-tint/50 p-4">
        <h2 className="text-[13.5px] font-medium text-context">The change</h2>
        <p className="mt-2 text-[15px]">Nothing was changed. This is a plain re-run from step {cmp.checkpoint.step_index + 1}.</p>
      </section>
    );
  }
  const before = (iv.original_arguments ?? iv.original_result ?? {}) as Record<string, unknown>;
  const after = (iv.arguments ?? iv.result ?? {}) as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return (
    <section className="rounded-[12px] border border-context/40 bg-context-tint/50 p-4" data-testid="change-card">
      <h2 className="text-[13.5px] font-medium text-context">The one change</h2>
      <p className="mt-1.5 text-[15px] font-semibold">
        Step {Number(iv.call_index) + 1}: {iv.type === "replace_tool_argument" ? "what the agent sent" : "what the tool answered"}
      </p>
      <dl className="mt-2 space-y-1 text-[13px]">
        {keys.map((k) => {
          const b = k in before ? JSON.stringify(before[k]) : null;
          const a = k in after ? JSON.stringify(after[k]) : null;
          if (b === a) return null;
          return (
            <div key={k} className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,2fr)] gap-2">
              <dt className="truncate font-mono text-fg-2">{k}</dt>
              <dd className="flex flex-wrap items-center gap-1.5 font-mono">
                {b !== null && <span className="text-fg-3 line-through">{b}</span>}
                {b !== null && a !== null && <Icon name="arrow" className="h-3 w-3 text-fg-3" />}
                {a !== null ? <span className="text-context">{a}</span> : <span className="font-sans text-bad">removed</span>}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

function cellText(side: StepSide): { title: string; ok: boolean; detail: string | null } {
  const args = (side.arguments && typeof side.arguments === "object" ? side.arguments : {}) as Record<string, unknown>;
  const ok = !side.error_code && side.status !== "error";
  const d = errorText(side.error_code).replace(/^(Rejected|No answer): /, "");
  return { title: toolTitle(side.tool ?? "tool", args), ok, detail: ok ? null : d[0].toUpperCase() + d.slice(1) };
}

/** Before and after as two rows of the same columns, so the split point is visible. */
function AlignedPaths({ cmp, mode }: { cmp: Comparison; mode: ViewMode }) {
  const split = cmp.first_divergence_call_index;
  return (
    <section className="rounded-[16px] border border-line bg-surface p-4">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Both flight paths, step by step</h2>
        <p className="text-[13px] text-fg-3">Each column is one step. Grey steps were kept from the original.</p>
      </div>
      <div className="path-scroll overflow-x-auto" data-testid="steps">
        <div className="grid min-w-max grid-flow-col gap-x-2" style={{ gridTemplateRows: "auto auto auto", gridTemplateColumns: `72px repeat(${cmp.steps.length}, 190px)` }}>
          <div />
          <div className="self-center text-[13px] font-medium text-fg-2">Before</div>
          <div className="self-center text-[13px] font-medium text-fg-2">After</div>
          {cmp.steps.map((s) => (
            <Column key={s.call_index} split={split === s.call_index}>
              <div className="flex h-7 items-center gap-1.5 text-[12.5px] text-fg-3">
                <span>Step {s.call_index + 1}</span>
                {split === s.call_index && <Pill tone="context">Paths split</Pill>}
              </div>
              <Cell side={s.source} mode={mode} />
              {s.inherited ? (
                <div className="mt-2 rounded-[10px] border border-dashed border-line p-2.5 text-[13px] text-fg-3">Same as before</div>
              ) : (
                <Cell side={s.fork} mode={mode} intervened={s.intervened} />
              )}
            </Column>
          ))}
        </div>
      </div>
    </section>
  );
}

function Column({ children, split }: { children: ReactNode; split: boolean }) {
  return <div className={`row-span-3 grid grid-rows-subgrid rounded-[12px] px-1 pb-1 ${split ? "bg-context-tint/40" : ""}`}>{children}</div>;
}

function Cell({ side, mode, intervened }: { side: StepSide | null; mode: ViewMode; intervened?: boolean }) {
  if (!side) return <div className="mt-2 rounded-[10px] border border-dashed border-line p-2.5 text-[13px] text-fg-3">No step</div>;
  const c = cellText(side);
  return (
    <div className={`mt-2 rounded-[10px] border p-2.5 ${intervened ? "border-context" : c.ok ? "border-line" : "border-bad/40"}`}>
      <p className="flex items-start gap-1.5 text-[13.5px] font-medium leading-[18px]">
        <Icon name={c.ok ? "check" : "x"} className={`mt-px h-3.5 w-3.5 shrink-0 ${c.ok ? "text-ok" : "text-bad"}`} />
        <span className="line-clamp-2">{c.title}</span>
      </p>
      {c.detail && <p className="mt-1 line-clamp-2 text-[12.5px] leading-4 text-bad">{c.detail}</p>}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {intervened && <Pill tone="context">Your change</Pill>}
        {side.error_code && <Tag>{side.error_code}</Tag>}
      </div>
      {mode === "technical" && <p className="mt-1 line-clamp-2 break-all font-mono text-[11px] leading-4 text-fg-2">{side.tool} {JSON.stringify(side.arguments)}</p>}
    </div>
  );
}
