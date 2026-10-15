"use client";

import { useState } from "react";
import { api, type Comparison, type ComparisonSide, type Graph, replayApi, type StepSide } from "@/lib/api";
import { fmtDuration, href, shortId } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { ExecutionGraph } from "./execution-graph";
import { Card, ErrorBox, Loading, StatusBadge, Tag } from "./ui";

type Loaded = { cmp: Comparison; sourceGraph: Graph; forkGraph: Graph };

async function load(jobId: string): Promise<Loaded> {
  const cmp = await replayApi.comparison(jobId);
  const [sourceGraph, forkGraph] = await Promise.all([api.graph(cmp.source.execution_id), api.graph(cmp.fork.execution_id)]);
  return { cmp, sourceGraph, forkGraph };
}

export function ComparisonView({ jobId }: { jobId: string }) {
  const { data, error, loading, reload } = useApi(() => load(jobId), jobId);
  return (
    <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Original vs fork</h1>
      {loading && !data && <Card className="mt-4"><Loading label="Loading comparison…" /></Card>}
      {error && <Card className="mt-4"><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Body data={data} />}
    </main>
  );
}

function Body({ data }: { data: Loaded }) {
  const { cmp, sourceGraph, forkGraph } = data;
  const [srcSel, setSrcSel] = useState<string | null>(null);
  const [forkSel, setForkSel] = useState<string | null>(null);
  const iv = cmp.intervention;
  const intervenedFork = cmp.steps.filter((s) => s.intervened && s.fork?.span_id).map((s) => s.fork!.span_id as string);
  return (
    <div className="mt-4 space-y-4" data-testid="comparison">
      <p className="text-sm text-muted">
        <span className="font-mono">{cmp.replay_level.replaceAll("_", " ")}</span> ·{" "}
        <span className="font-mono">{cmp.replay_mode}</span> · resumed from the checkpoint before call #{cmp.checkpoint.step_index}
        {cmp.first_divergence_call_index !== null && <> · first divergence at call #{cmp.first_divergence_call_index}</>}
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <Outcome title="Original" side={cmp.source} />
        <Outcome title="Fork" side={cmp.fork} testId="fork-outcome" />
      </div>

      <Card title="Intervention record (exactly what was changed)">
        {iv ? (
          <div className="grid gap-3 px-4 py-3 text-sm md:grid-cols-3">
            <div><p className="text-xs text-muted">Type</p><p className="font-mono">{String(iv.type)}</p></div>
            <div><p className="text-xs text-muted">Target</p><p className="font-mono">call #{String(iv.call_index)} · {String(iv.tool)}</p></div>
            <div><p className="text-xs text-muted">Span</p><p className="font-mono">{String(iv.target_span_id)}</p></div>
            {"original_arguments" in iv && (
              <div className="md:col-span-1"><p className="text-xs text-muted">Before</p><Json value={iv.original_arguments} /></div>
            )}
            <div className="md:col-span-2"><p className="text-xs text-muted">After</p><Json value={iv.arguments ?? iv.result} /></div>
          </div>
        ) : (
          <p className="px-4 py-3 text-sm text-muted">No intervention: plain checkpoint replay (level 2).</p>
        )}
      </Card>

      <Card title="Steps (aligned by tool-call index)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm" data-testid="steps">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr><th className="px-4 py-2">#</th><th className="px-2 py-2">Original</th><th className="px-2 py-2">Fork</th><th className="px-4 py-2">Note</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {cmp.steps.map((s) => (
                <tr key={s.call_index} className={s.intervened ? "bg-warn/10" : s.changed ? "bg-line/40" : ""}>
                  <td className="px-4 py-2 font-mono text-xs">{s.call_index}</td>
                  <td className="px-2 py-2"><StepCell side={s.source} /></td>
                  <td className="px-2 py-2"><StepCell side={s.inherited ? null : s.fork} inherited={s.inherited} /></td>
                  <td className="px-4 py-2 text-xs text-muted">
                    {s.inherited ? "before checkpoint (not re-run)" : s.intervened ? "intervened" : s.changed ? "differs" : "same"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Final sandbox state diff">
        {cmp.state_diff === null ? (
          <p className="px-4 py-3 text-sm text-muted">{cmp.state_diff_note}</p>
        ) : cmp.state_diff.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">Identical final sandbox state.</p>
        ) : (
          <table className="w-full text-sm" data-testid="state-diff">
            <thead className="text-left text-xs text-muted"><tr><th className="px-4 py-2">Path</th><th className="px-2 py-2">Change</th><th className="px-2 py-2">Original</th><th className="px-4 py-2">Fork</th></tr></thead>
            <tbody className="divide-y divide-line">
              {cmp.state_diff.map((d) => (
                <tr key={d.path}>
                  <td className="px-4 py-2 font-mono text-xs">{d.path}</td>
                  <td className="px-2 py-2 text-xs">{d.change}</td>
                  <td className="px-2 py-2 font-mono text-xs text-bad">{d.source === null ? "—" : JSON.stringify(d.source)}</td>
                  <td className="px-4 py-2 font-mono text-xs text-ok">{d.fork === null ? "—" : JSON.stringify(d.fork)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Original graph · ${shortId(cmp.source.execution_id)}`}>
          <ExecutionGraph graph={sourceGraph} selected={srcSel} onSelect={setSrcSel} height="h-[480px]" testId="source-graph" />
        </Card>
        <Card title={`Fork graph · ${shortId(cmp.fork.execution_id)} (re-executed suffix only)`}>
          <ExecutionGraph graph={forkGraph} selected={forkSel} onSelect={setForkSel} intervenedSpans={intervenedFork} height="h-[480px]" testId="fork-graph" />
        </Card>
      </div>

      <p className="text-xs text-muted" data-testid="caveat">{cmp.caveat}</p>
    </div>
  );
}

function Outcome({ title, side, testId }: { title: string; side: ComparisonSide; testId?: string }) {
  const m = side.metrics;
  return (
    <Card title={title}>
      <div className="space-y-2 px-4 py-3 text-sm" data-testid={testId}>
        <p className="flex flex-wrap items-center gap-2">
          <StatusBadge status={side.status} />
          <a className="font-mono text-xs hover:underline" href={href(`/runs/${side.execution_id}`)}>{side.execution_id}</a>
        </p>
        <p>
          Verifier:{" "}
          <b className={side.verifier?.passed ? "text-ok" : "text-bad"} data-testid="verifier">{side.verifier?.passed ? "passed" : "failed"}</b>
          {side.verifier?.reasons && side.verifier.reasons.length > 0 && <span className="text-muted"> ({side.verifier.reasons.join(", ")})</span>}
          {" · "}termination <span className="font-mono">{side.termination}</span>
        </p>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div><dt className="text-muted">Tool calls recorded</dt><dd className="font-mono">{m.tool_calls_recorded ?? "—"}</dd></div>
          <div><dt className="text-muted">Tool errors</dt><dd className="font-mono">{m.tool_errors ?? "—"}</dd></div>
          <div><dt className="text-muted">Model calls recorded</dt><dd className="font-mono">{m.llm_calls_recorded ?? "—"}</dd></div>
          <div><dt className="text-muted">Duration</dt><dd className="font-mono">{fmtDuration(m.duration_ms)}</dd></div>
          <div><dt className="text-muted">Tokens</dt><dd className="font-mono">{m.tokens ?? "— (stub)"}</dd></div>
          <div><dt className="text-muted">Est. cost</dt><dd className="font-mono">{m.estimated_cost_usd ?? "— (no price table)"}</dd></div>
        </dl>
        <div className="flex flex-wrap gap-1">
          {side.findings.length === 0 ? <span className="text-xs text-muted">No findings</span> :
            side.findings.map((f) => <Tag key={f.category + f.title}>{f.category}</Tag>)}
        </div>
      </div>
    </Card>
  );
}

function StepCell({ side, inherited }: { side: StepSide | null; inherited?: boolean }) {
  if (inherited) return <span className="text-xs text-muted">inherited</span>;
  if (!side) return <span className="text-xs text-muted">—</span>;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-xs">{side.tool}</span>
      <span className="font-mono text-[11px] text-muted">{JSON.stringify(side.arguments)}</span>
      {side.error_code ? <Tag>{side.error_code}</Tag> : <span className="text-xs text-ok">ok</span>}
    </span>
  );
}

function Json({ value }: { value: unknown }) {
  return <pre className="mt-1 overflow-auto rounded bg-ink px-3 py-2 font-mono text-[11px] text-[#c9d1d9]">{JSON.stringify(value, null, 2)}</pre>;
}
