"use client";

import { useEffect, useState } from "react";
import { type EvalBlock, type EvalSummary, evalApi, type RateOut } from "@/lib/api";
import { href } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { useViewMode } from "@/lib/view-mode";
import { symptomLabel } from "@/lib/story";
import { Card, ErrorBox, Icon, Kpi, Loading, Pill, Segmented } from "./ui";

type Split = "all" | "dev" | "heldout";

const FAMILY: Record<string, string> = {
  control_exchange: "Control: exchange",
  control_refund: "Control: refund",
  control_recovered_timeout: "Control: timeout, then recovers",
  invalid_argument: "Wrong input (product name)",
  repeat_loop: "Wrong input, repeated (order id)",
  persistent_timeout: "System never answers",
  stale_retrieval: "Stale data",
  wrong_identity: "Mixed-up orders",
};

function pct(r: RateOut | undefined): string {
  return r && r.rate !== null ? `${Math.round(r.rate * 100)}%` : "–";
}

function frac(r: RateOut | undefined): string {
  return r && r.n ? `${r.k} of ${r.n}` : "no runs";
}

function hint(r: RateOut, unit = ""): string {
  if (!r.n) return "no runs";
  const c = ci(r);
  return `${r.k} of ${r.n}${unit}${c ? `, ${c}` : ""}`;
}

function ci(r: RateOut | undefined): string {
  return r && r.ci_low !== null && r.ci_high !== null
    ? `95% CI ${Math.round(r.ci_low * 100)}–${Math.round(r.ci_high * 100)}%`
    : "";
}

export function BenchmarkView() {
  const sources = useApi(() => evalApi.sources(), "eval-sources");
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    // Default to the most complete results (most cases), newest first among equals.
    if (!source && sources.data?.length) {
      const best = [...sources.data].sort((a, b) => b.cases - a.cases)[0];
      setSource(best.source);
    }
  }, [sources.data, source]);
  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[30px] font-semibold leading-9 tracking-tight">Benchmark</h1>
          <p className="mt-0.5 max-w-3xl text-fg-2">
            Synthetic support tickets in eight families. Each failed run is restarted three ways: with FlightPath&apos;s
            suggested change, with a random valid change, and with no change. Pass or fail is decided by the outcome check.
          </p>
        </div>
        {sources.data && sources.data.length > 1 && (
          <label className="text-[14px] text-fg-2">Results
            <select aria-label="Benchmark results" value={source ?? ""} onChange={(e) => setSource(e.target.value)}
              className="ml-1.5 max-w-[320px] rounded-[8px] border border-line-strong bg-surface px-2 py-1 text-fg">
              {sources.data.map((s) => (
                <option key={s.source} value={s.source}>{s.model_id} ({s.benchmark_version}, seed {s.seed})</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {sources.loading && !sources.data && <Card><Loading label="Loading results…" /></Card>}
      {sources.error && <Card><ErrorBox message={sources.error} onRetry={sources.reload} /></Card>}
      {sources.data && sources.data.length === 0 && <EmptyBenchmark />}
      {source && <SourceView key={source} source={source} />}
    </main>
  );
}

function EmptyBenchmark() {
  return (
    <Card>
      <div className="p-6" data-testid="benchmark-empty">
        <p className="text-[17px] font-semibold">No benchmark results yet</p>
        <p className="mt-1 max-w-2xl text-fg-2">Run the benchmark (about ten seconds on a CPU) and load it into the app:</p>
        <pre className="mt-3 w-fit rounded-[8px] bg-well px-3 py-2 font-mono text-[13px]">make benchmark{"\n"}make benchmark-import</pre>
      </div>
    </Card>
  );
}

function SourceView({ source }: { source: string }) {
  const s = useApi(() => evalApi.summary(source), source);
  const [split, setSplit] = useState<Split>("all");
  if (s.loading && !s.data) return <Card><Loading label="Loading results…" /></Card>;
  if (s.error) return <Card><ErrorBox message={s.error} onRetry={s.reload} /></Card>;
  if (!s.data) return null;
  const d = s.data;
  const b = d.splits[split] ?? d.splits.all;
  if (!b) return null;
  return (
    <div className="space-y-4" data-testid="benchmark">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented label="Cases" value={split} onChange={setSplit} testId="split"
          options={[{ id: "all", label: "All cases" }, { id: "dev", label: "Dev" }, { id: "heldout", label: "Held-out" }]} />
        <p className="text-[13.5px] text-fg-2">
          Agent <span className="text-fg">{d.model_id}</span>, {d.cases} cases, {d.runs} runs, seed {d.seed}
          {d.model_revision ? <>, revision <span className="font-mono text-[12.5px]">{d.model_revision.slice(0, 12)}</span></> : null}
        </p>
        <a href={evalApi.csvUrl(source)} className="ml-auto text-[14px] text-fg-2 underline underline-offset-4 hover:text-fg">Download all runs (CSV)</a>
      </div>

      <div data-testid="benchmark-kpis" className="grid grid-cols-2 overflow-hidden rounded-[12px] border border-line bg-surface md:grid-cols-4 md:divide-x md:divide-line">
        <Kpi label="Baseline success" value={pct(b.success)} hint={`${frac(b.success)} runs passed`} />
        <Kpi label="Failed runs fixed by FlightPath's change" value={pct(b.repair_recovery)} hint={hint(b.repair_recovery)} />
        <Kpi label="Fixed by a random valid change" value={pct(b.random_recovery)} hint={hint(b.random_recovery, " tries")} />
        <Kpi label="Replays that reproduce the run" value={pct(b.replay_validity)} hint={hint(b.replay_validity)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <RecoveryChart b={b} />
        <Notes b={b} />
      </div>

      <FamilyTable d={d} />
      <DetectorTable b={b} />
      <CaseTable d={d} split={split} />
    </div>
  );
}

/** One measure (recovery of failed runs), three conditions: one hue, CI whiskers, direct labels. */
function RecoveryChart({ b }: { b: EvalBlock }) {
  const rows: [string, RateOut][] = [
    ["FlightPath's suggested change", b.repair_recovery],
    ["Random valid change", b.random_recovery],
    ["Restart, nothing changed", b.no_change_recovery],
  ];
  return (
    <Card title="Recovery of failed runs, by change">
      <div className="px-4 pb-4 pt-3" data-testid="recovery-chart">
        <p className="mb-3 text-[13px] text-fg-2">Share of {b.failed_runs} failed runs that pass after restarting with one change. Lines show the 95% interval.</p>
        <div className="space-y-3">
          {rows.map(([label, r]) => (
            <div key={label} className="grid grid-cols-[minmax(0,170px)_minmax(0,1fr)_92px] items-center gap-3"
              title={`${label}: ${pct(r)} (${frac(r)}; ${ci(r)})`}>
              <span className="text-[14px] leading-5">{label}</span>
              <div className="relative h-5 rounded-[4px] bg-well">
                {r.rate !== null && (
                  <>
                    <div className="absolute inset-y-0 left-0 rounded-[4px] bg-context" style={{ width: `${Math.max(r.rate * 100, 0.6)}%` }} />
                    <div className="absolute top-1/2 h-px -translate-y-1/2 bg-fg"
                      style={{ left: `${(r.ci_low ?? 0) * 100}%`, width: `${((r.ci_high ?? 0) - (r.ci_low ?? 0)) * 100}%` }} />
                    {[r.ci_low, r.ci_high].map((v, i) => (
                      <div key={i} className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-fg" style={{ left: `${(v ?? 0) * 100}%` }} />
                    ))}
                  </>
                )}
              </div>
              <span className="num text-[15px]"><b className="font-semibold">{pct(r)}</b> <span className="text-fg-2">{r.k}/{r.n}</span></span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function Notes({ b }: { b: EvalBlock }) {
  return (
    <Card title="How to read this">
      <ul className="space-y-2 px-4 py-3 text-[14px] leading-5 text-fg-2">
        <li><span className="text-fg">Controls.</span> A change only counts if it beats both a random change ({pct(b.random_recovery)}) and restarting with nothing changed ({pct(b.no_change_recovery)}).</li>
        <li><span className="text-fg">Coverage.</span> FlightPath proposed a change for {frac(b.repair_coverage)} failed runs.{b.repair_coverage.k < b.repair_coverage.n ? " The rest, where no detector or repair rule applied, count as not recovered." : ""}</li>
        <li><span className="text-fg">False benefit.</span> {b.false_benefit.n ? `${b.false_benefit.k} of ${b.false_benefit.n} recoveries would have happened without the change.` : "No recoveries to check."}</li>
        <li><span className="text-fg">Honesty.</span> Cases are synthetic and the rules were written by the same team. The held-out split was not used to write them. With the scripted agent each run is exact; real-model runs repeat each case with several seeds.</li>
      </ul>
    </Card>
  );
}

function FamilyTable({ d }: { d: EvalSummary }) {
  return (
    <Card title="By failure family">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[14px]" data-testid="family-table">
          <thead className="border-b border-line text-left text-[13px] text-fg-2">
            <tr><th className="px-4 py-2 font-medium">Family</th><th className="px-2 py-2 font-medium">Cases</th><th className="px-2 py-2 font-medium">Baseline success</th><th className="px-2 py-2 font-medium">Fixed by FlightPath</th><th className="px-4 py-2 font-medium">Fixed by a random change</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {d.families.map((f) => (
              <tr key={f.family}>
                <td className="px-4 py-2">{FAMILY[f.family] ?? f.family}</td>
                <td className="num px-2 py-2">{f.cases}</td>
                <td className="px-2 py-2"><RateCell r={f.success} /></td>
                <td className="px-2 py-2"><RateCell r={f.repair_recovery} /></td>
                <td className="px-4 py-2"><RateCell r={f.random_recovery} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RateCell({ r }: { r: RateOut }) {
  if (!r.n) return <span className="text-fg-3">not applicable</span>;
  return (
    <span title={ci(r)}>
      <span className="num font-medium">{pct(r)}</span> <span className="text-[13px] text-fg-2">{r.k}/{r.n}</span>
    </span>
  );
}

function DetectorTable({ b }: { b: EvalBlock }) {
  const det = b.detectors;
  return (
    <Card title="Failure detectors" aside={<span className="text-[13px] text-fg-2">fired on {frac(det.coverage_on_failed)} failed runs{det.false_alarm_on_passed.n ? ` and ${frac(det.false_alarm_on_passed)} passed runs` : ""}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[14px]" data-testid="detector-table">
          <thead className="border-b border-line text-left text-[13px] text-fg-2">
            <tr><th className="px-4 py-2 font-medium">Detector</th><th className="px-2 py-2 font-medium">Correct</th><th className="px-2 py-2 font-medium">False alarms</th><th className="px-2 py-2 font-medium">Missed</th><th className="px-2 py-2 font-medium">Precision</th><th className="px-4 py-2 font-medium">Recall</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {Object.entries(det.per_category).map(([cat, v]) => (
              <tr key={cat}>
                <td className="px-4 py-2 font-mono text-[12.5px]">{cat}</td>
                <td className="num px-2 py-2">{v.tp}</td>
                <td className={`num px-2 py-2 ${v.fp ? "text-warn" : ""}`}>{v.fp}</td>
                <td className={`num px-2 py-2 ${v.fn ? "text-bad" : ""}`}>{v.fn}</td>
                <td className="px-2 py-2"><RateCell r={v.precision} /></td>
                <td className="px-4 py-2"><RateCell r={v.recall} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {det.failure_causes && Object.keys(det.failure_causes).length > 0 && (
        <p className="border-t border-line px-4 py-3 text-[13px] text-fg-2" data-testid="failure-causes">
          Failed runs by most likely cause:{" "}
          {Object.entries(det.failure_causes)
            .map(([cat, n]) => `${cat === "none" ? "nothing detected" : symptomLabel(cat)} ${n}`)
            .join(" · ")}
        </p>
      )}
    </Card>
  );
}

function Outcome({ cell }: { cell?: { passed: boolean; skipped: string | null } }) {
  if (!cell) return <span className="text-fg-3">–</span>;
  if (cell.skipped) return <Pill tone="neutral">no change proposed</Pill>;
  return cell.passed
    ? <span className="inline-flex items-center gap-1 text-ok"><Icon name="check" className="h-3.5 w-3.5" />passed</span>
    : <span className="inline-flex items-center gap-1 text-bad"><Icon name="x" className="h-3.5 w-3.5" />failed</span>;
}

function CaseTable({ d, split }: { d: EvalSummary; split: Split }) {
  const [mode] = useViewMode();
  const [open, setOpen] = useState(false);
  const rows = d.case_rows.filter((c) => split === "all" || c.split === split);
  return (
    <details className="rounded-[12px] border border-line bg-surface" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)} data-testid="case-table">
      <summary className="cursor-pointer px-4 py-3 font-semibold">Every case <span className="font-normal text-fg-2">({rows.length})</span></summary>
      {open && (
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[860px] text-[14px]">
            <thead className="border-b border-line text-left text-[13px] text-fg-2">
              <tr><th className="px-4 py-2 font-medium">Case</th><th className="px-2 py-2 font-medium">Family</th><th className="px-2 py-2 font-medium">Baseline</th><th className="px-2 py-2 font-medium">FlightPath&apos;s change</th><th className="px-2 py-2 font-medium">Random changes</th><th className="px-4 py-2 font-medium">Recorded runs</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((c) => (
                <tr key={c.case_id}>
                  <td className="px-4 py-2 font-mono text-[12.5px]">{c.case_id}{c.split === "heldout" && <span className="ml-2 font-sans"><Pill tone="neutral">held-out</Pill></span>}</td>
                  <td className="px-2 py-2 text-fg-2">{FAMILY[c.family] ?? c.family}</td>
                  <td className="px-2 py-2"><Outcome cell={c.baseline} />{mode === "technical" && c.baseline?.findings?.length ? <span className="block font-mono text-[11.5px] text-fg-3">{c.baseline.findings.join(", ")}</span> : null}</td>
                  <td className="px-2 py-2"><Outcome cell={c.repair} />{c.repair?.intervention && <span className="block text-[12.5px] text-fg-2">{c.repair.intervention}</span>}</td>
                  <td className="num px-2 py-2">{c.random ? `${c.random.filter(Boolean).length}/${c.random.length} passed` : <span className="text-fg-3">–</span>}</td>
                  <td className="px-4 py-2">
                    {c.baseline?.execution_id ? (
                      <span className="flex gap-3">
                        <a className="underline underline-offset-4" href={href(`/runs/${c.baseline.execution_id}`)}>baseline</a>
                        {c.repair?.execution_id && <a className="underline underline-offset-4" href={href(`/runs/${c.repair.execution_id}`)}>with change</a>}
                      </span>
                    ) : <span className="text-[13px] text-fg-3">not imported</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}
