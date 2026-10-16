"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, liveApi, type ExecutionSummary } from "@/lib/api";
import { agentLabel, timeAgo } from "@/lib/describe";
import { fmtDuration, fmtTime, href, SINCE_OPTIONS, shortId, sinceToIso } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Card, EmptyRuns, ErrorBox, Kpi, Loading, Pill, StatusBadge } from "./ui";

const PROBLEMS: Record<string, string> = {
  SKU_REQUIRED: "wrong input to the stock check",
  INVALID_ARGUMENT: "a tool rejected its input",
  TIMEOUT: "a system timed out",
  ORDER_NOT_FOUND: "order not found",
  SKU_NOT_FOUND: "unknown product code",
  UNKNOWN_TOOL: "called a tool that doesn't exist",
};

function topProblem(tags: Record<string, number> | undefined): string | null {
  if (!tags) return null;
  const top = Object.entries(tags).sort((a, b) => b[1] - a[1])[0];
  if (!top) return null;
  const label = PROBLEMS[top[0]] ?? top[0].toLowerCase().replaceAll("_", " ");
  return label[0].toUpperCase() + label.slice(1);
}

function problemLine(r: ExecutionSummary): string {
  const parts = r.error_codes.map((c) => PROBLEMS[c] ?? c.toLowerCase().replaceAll("_", " "));
  if (r.termination === "budget_exhausted") parts.push("ran out of steps");
  if (!parts.length && r.status === "failed") parts.push("wrong outcome");
  return parts.join(", ");
}

const PAGE = 20;
type Filters = { status: string; version: string; since: string; page: number };
const DEFAULTS: Filters = { status: "", version: "", since: "", page: 0 };

function readFilters(): Filters {
  const q = new URLSearchParams(window.location.search);
  return {
    status: q.get("status") ?? "",
    version: q.get("version") ?? "",
    since: q.get("since") ?? "",
    page: Math.max(0, Number(q.get("page") ?? 0) || 0),
  };
}

function writeFilters(f: Filters) {
  const q = new URLSearchParams();
  if (f.status) q.set("status", f.status);
  if (f.version) q.set("version", f.version);
  if (f.since) q.set("since", f.since);
  if (f.page) q.set("page", String(f.page));
  const url = `${window.location.pathname}${q.size ? `?${q}` : ""}`;
  window.history.replaceState(null, "", url);
}

export function RunsExplorer() {
  const [filters, setFilters] = useState<Filters | null>(null);
  useEffect(() => setFilters(readFilters()), []);
  const f = filters ?? DEFAULTS;
  const update = (patch: Partial<Filters>) => {
    const next = { ...f, page: 0, ...patch };
    setFilters(next);
    writeFilters(next);
  };

  const versions = useApi(() => api.agentVersions(), "versions");
  const cfg = useApi(() => liveApi.config(), "live-config");
  const stats = useApi(() => api.overview(sinceToIso(f.since)), `overview-${f.since}`);
  const titleOf = (task: string) => cfg.data?.scenarios.find((s) => s.fixture_id === task)?.title ?? task.replaceAll("_", " ");
  const runs = useApi(
    () =>
      api.executions({
        status: f.status || undefined,
        agent_version_id: f.version || undefined,
        since: sinceToIso(f.since),
        limit: PAGE,
        offset: f.page * PAGE,
      }),
    filters ? JSON.stringify(f) : "init",
  );

  const rows = useRef<(HTMLTableRowElement | null)[]>([]);
  const open = (id: string) => window.location.assign(href(`/runs/${id}`));
  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, i: number, id: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open(id);
    } else if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      rows.current[i + 1]?.focus();
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      rows.current[i - 1]?.focus();
    }
  };

  const total = runs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const select = "ml-1.5 rounded-[8px] border border-line-strong bg-surface px-2 py-1 text-fg";

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[30px] font-semibold leading-9 tracking-tight">Runs</h1>
          <p className="mt-0.5 text-fg-2">Every recorded run, newest first. Open one to see its flight path.</p>
        </div>
        <div className="flex flex-wrap gap-3 text-[14px] text-fg-2">
          <label>Status
            <select aria-label="Status" value={f.status} onChange={(e) => update({ status: e.target.value })} className={select}>
              <option value="">All</option>
              <option value="succeeded">Passed</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label>Agent
            <select aria-label="Agent version" value={f.version} onChange={(e) => update({ version: e.target.value })} className={`${select} max-w-[220px]`}>
              <option value="">All</option>
              {(versions.data ?? []).map((v) => (
                <option key={v.id} value={v.id}>{agentLabel(v.model_name)} ({v.git_sha.slice(0, 7)})</option>
              ))}
            </select>
          </label>
          <label>Time
            <select aria-label="Time range" value={f.since} onChange={(e) => update({ since: e.target.value })} className={select}>
              {SINCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div data-testid="kpis" className="mb-4 grid grid-cols-2 overflow-hidden rounded-[12px] border border-line bg-surface md:grid-cols-4 md:divide-x md:divide-line">
        <Kpi label="Runs recorded" value={stats.data ? String(stats.data.total) : "–"}
          hint={stats.data ? `${stats.data.succeeded} passed, ${stats.data.failed} failed` : undefined} />
        <Kpi label="Pass rate" value={stats.data?.success_rate != null ? `${Math.round(stats.data.success_rate * 100)}%` : "–"} />
        <Kpi label="Median run time" value={stats.data ? fmtDuration(stats.data.median_duration_ms) : "–"} />
        <Kpi label="Most common problem" value={topProblem(stats.data?.failure_tags) ?? "None"}
          hint={topProblem(stats.data?.failure_tags) ? "across failed runs" : undefined} />
      </div>

      <Card>
        {runs.loading && !runs.data && <Loading label="Loading runs…" />}
        {runs.error && <ErrorBox message={runs.error} onRetry={runs.reload} />}
        {runs.data && total === 0 && (f.status || f.version || f.since ? (
          <p className="px-5 py-10 text-muted">No runs match these filters.</p>
        ) : <EmptyRuns />)}
        {runs.data && total > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="border-b border-line text-left text-[13px] text-fg-2">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Result</th>
                  <th className="px-2 py-2.5 font-medium">Situation</th>
                  <th className="px-2 py-2.5 font-medium">Agent</th>
                  <th className="px-2 py-2.5 font-medium">Steps</th>
                  <th className="px-5 py-2.5 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.data.items.map((r, i) => (
                  <tr
                    key={r.id}
                    ref={(el) => { rows.current[i] = el; }}
                    tabIndex={0}
                    data-testid="run-row"
                    data-task={r.task_id}
                    onClick={() => open(r.id)}
                    onKeyDown={(e) => onRowKey(e, i, r.id)}
                    className="cursor-pointer hover:bg-canvas focus:bg-canvas focus:outline-none"
                  >
                    <td className="px-5 py-3 align-top"><StatusBadge status={r.status} /></td>
                    <td className="px-2 py-3">
                      <a href={href(`/runs/${r.id}`)} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline">
                        {titleOf(r.task_id)}
                      </a>
                      {r.parent_execution_id && (
                        <span className="ml-2" title={`re-run of ${r.parent_execution_id}`}><Pill tone="context">Re-run</Pill></span>
                      )}
                      {problemLine(r) && <span className="block text-[14px] text-bad">{problemLine(r)}</span>}
                      <span className="sr-only">{r.error_codes.join(" ")}</span>
                    </td>
                    <td className="px-2 py-3 text-[15px] text-muted">{agentLabel(r.agent_version.model_name)}</td>
                    <td className="px-2 py-3 text-[15px]" title={fmtDuration(r.duration_ms)}>{r.tool_calls}</td>
                    <td className="px-5 py-3 text-right text-[15px] text-muted" title={`${fmtTime(r.started_at)} · run ${shortId(r.id)}`}>{timeAgo(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {runs.data && total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-sm text-muted">
            <span>Page {f.page + 1} of {pages}</span>
            <div className="flex gap-2">
              <button type="button" disabled={f.page === 0} onClick={() => update({ page: f.page - 1 })}
                className="rounded-md border border-line px-3 py-1 hover:border-muted disabled:opacity-40">Previous</button>
              <button type="button" disabled={f.page + 1 >= pages} onClick={() => update({ page: f.page + 1 })}
                className="rounded-md border border-line px-3 py-1 hover:border-muted disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </Card>
    </main>
  );
}
