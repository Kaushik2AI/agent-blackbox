"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import { fmtDuration, fmtTime, href, SINCE_OPTIONS, shortId, sinceToIso } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Card, EmptyRuns, ErrorBox, Loading, StatusBadge, Tag } from "./ui";

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
  const select = "rounded border border-line bg-panel px-2 py-1 text-[#e6edf3]";

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="mt-1 text-sm text-muted">
            Every recorded execution. Use ↑/↓ to move between rows and Enter to open one.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 text-sm text-muted">
          <label>Status{" "}
            <select aria-label="Status" value={f.status} onChange={(e) => update({ status: e.target.value })} className={select}>
              <option value="">All</option>
              {["succeeded", "failed", "running", "aborted", "pending"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Version{" "}
            <select aria-label="Agent version" value={f.version} onChange={(e) => update({ version: e.target.value })} className={select}>
              <option value="">All</option>
              {(versions.data ?? []).map((v) => (
                <option key={v.id} value={v.id}>{v.agent} @ {v.git_sha.slice(0, 7)} · {v.model_name}</option>
              ))}
            </select>
          </label>
          <label>Time{" "}
            <select aria-label="Time range" value={f.since} onChange={(e) => update({ since: e.target.value })} className={select}>
              {SINCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>
      </div>

      <Card>
        {runs.loading && !runs.data && <Loading label="Loading runs…" />}
        {runs.error && <ErrorBox message={runs.error} onRetry={runs.reload} />}
        {runs.data && total === 0 && (f.status || f.version || f.since ? (
          <p className="px-4 py-10 text-sm text-muted">No runs match these filters.</p>
        ) : <EmptyRuns />)}
        {runs.data && total > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-2 py-2 font-medium">Task</th>
                  <th className="px-2 py-2 font-medium">Run</th>
                  <th className="px-2 py-2 font-medium">Version</th>
                  <th className="px-2 py-2 font-medium">Duration</th>
                  <th className="px-2 py-2 font-medium">Tool calls</th>
                  <th className="px-2 py-2 font-medium">Failure tags</th>
                  <th className="px-4 py-2 font-medium">Started</th>
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
                    className="cursor-pointer hover:bg-line/50 focus:bg-line/70 focus:outline-none"
                  >
                    <td className="px-4 py-2.5"><StatusBadge status={r.status} /></td>
                    <td className="px-2 py-2.5 font-mono text-xs">
                      <a href={href(`/runs/${r.id}`)} onClick={(e) => e.stopPropagation()} className="hover:underline">{r.task_id}</a>
                      {r.parent_execution_id && <span className="ml-2 rounded border border-warn/50 px-1 text-[10px] text-warn" title={`fork of ${r.parent_execution_id}`}>fork</span>}
                    </td>
                    <td className="px-2 py-2.5 font-mono text-xs text-muted" title={r.id}>{shortId(r.id)}</td>
                    <td className="px-2 py-2.5 font-mono text-xs text-muted">{r.agent_version.git_sha.slice(0, 7)}</td>
                    <td className="px-2 py-2.5 font-mono text-xs">{fmtDuration(r.duration_ms)}</td>
                    <td className="px-2 py-2.5 font-mono text-xs">{r.tool_calls}</td>
                    <td className="px-2 py-2.5"><div className="flex flex-wrap gap-1">{r.error_codes.map((c) => <Tag key={c}>{c}</Tag>)}</div></td>
                    <td className="px-4 py-2.5 text-xs text-muted">{fmtTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {runs.data && total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-muted">
            <span>{total} run{total === 1 ? "" : "s"} · page {f.page + 1} of {pages}</span>
            <div className="flex gap-2">
              <button type="button" disabled={f.page === 0} onClick={() => update({ page: f.page - 1 })}
                className="rounded border border-line px-2.5 py-1 hover:bg-line disabled:opacity-40">Previous</button>
              <button type="button" disabled={f.page + 1 >= pages} onClick={() => update({ page: f.page + 1 })}
                className="rounded border border-line px-2.5 py-1 hover:bg-line disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </Card>
    </main>
  );
}
