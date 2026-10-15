"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDuration, href, pct, SINCE_OPTIONS, sinceToIso } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Card, EmptyRuns, ErrorBox, Kpi, Loading, Tag } from "./ui";

export function OverviewView() {
  const [since, setSince] = useState("");
  const { data, error, loading, reload } = useApi(() => api.overview(sinceToIso(since)), since);

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="mt-1 text-sm text-muted">Computed from recorded executions in the database.</p>
        </div>
        <label className="text-sm text-muted">
          Time range{" "}
          <select value={since} onChange={(e) => setSince(e.target.value)}
            className="ml-1 rounded border border-line bg-panel px-2 py-1 text-[#e6edf3]">
            {SINCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      </div>

      {loading && !data && <Card><Loading /></Card>}
      {error && <Card><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && data.total === 0 && <Card><EmptyRuns /></Card>}
      {data && data.total > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" data-testid="kpis">
            <Kpi label="Runs" value={String(data.total)} />
            <Kpi label="Success rate" value={pct(data.success_rate)}
              hint={`${data.succeeded} succeeded / ${data.succeeded + data.failed} finished`} />
            <Kpi label="Failed" value={String(data.failed)} />
            <Kpi label="Median duration" value={fmtDuration(data.median_duration_ms)} />
            <Kpi label="Token spend" value={data.total_tokens === null ? "—" : String(data.total_tokens)}
              hint={data.total_tokens === null ? "no token usage reported (stub model)" : undefined} />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Card title="Failure tags (tool error codes)">
              {Object.keys(data.failure_tags).length === 0 ? (
                <p className="px-4 py-6 text-sm text-muted">No tool errors recorded.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {Object.entries(data.failure_tags).map(([tag, n]) => {
                    const max = Math.max(...Object.values(data.failure_tags));
                    return (
                      <li key={tag} className="flex items-center gap-3 px-4 py-2.5">
                        <span className="w-40 shrink-0"><Tag>{tag}</Tag></span>
                        <div className="h-1.5 flex-1 rounded bg-line" aria-hidden>
                          <div className="h-1.5 rounded bg-bad/70" style={{ width: `${(n / max) * 100}%` }} />
                        </div>
                        <span className="w-16 text-right font-mono text-sm">{n} run{n === 1 ? "" : "s"}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>

            <Card title="By task">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr><th className="px-4 py-2 font-medium">Task</th><th className="px-2 py-2 font-medium">Succeeded</th><th className="px-2 py-2 font-medium">Failed</th><th className="px-4 py-2 text-right font-medium">Runs</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(data.by_task).map(([task, counts]) => (
                    <tr key={task}>
                      <td className="px-4 py-2 font-mono text-xs">{task}</td>
                      <td className="px-2 py-2 font-mono text-ok">{counts.succeeded ?? 0}</td>
                      <td className="px-2 py-2 font-mono text-bad">{counts.failed ?? 0}</td>
                      <td className="px-4 py-2 text-right font-mono">{Object.values(counts).reduce((a, b) => a + b, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
          <p className="mt-6 text-sm">
            <a className="text-ok underline-offset-4 hover:underline" href={href("/runs")}>Explore all runs →</a>
          </p>
        </>
      )}
    </main>
  );
}
