"use client";

import { useMemo, useState } from "react";
import {
  api,
  type EventOut,
  type ExecutionDetail,
  type Finding,
  type Graph,
  type ReplayJob,
  replayApi,
  type Timeline,
} from "@/lib/api";
import { fmtDuration, fmtTime, href, shortId } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { ExecutionGraph } from "./execution-graph";
import { Card, ErrorBox, Loading, StatusBadge, Tag } from "./ui";

type Loaded = {
  detail: ExecutionDetail;
  timeline: Timeline;
  graph: Graph;
  findings: Finding[];
  replays: ReplayJob[];
};

async function loadAll(id: string): Promise<Loaded> {
  const [detail, timeline, graph, findings, replays] = await Promise.all([
    api.execution(id), api.timeline(id), api.graph(id), replayApi.findings(id), replayApi.replaysOf(id),
  ]);
  return { detail, timeline, graph, findings: findings.findings, replays };
}

export function Inspector({ id }: { id: string }) {
  const { data, error, loading, reload } = useApi(() => loadAll(id), id);
  return (
    <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">
      <p className="mb-3 text-sm"><a href={href("/runs")} className="text-muted hover:text-[#e6edf3]">← All runs</a></p>
      {loading && !data && <Card><Loading label="Loading execution…" /></Card>}
      {error && <Card><ErrorBox message={error} onRetry={reload} /></Card>}
      {data && <Loaded data={data} />}
    </main>
  );
}

function Loaded({ data }: { data: Loaded }) {
  const { detail, timeline, graph, findings, replays } = data;
  const root = graph.nodes.find((n) => n.parent_span_id === null) ?? graph.nodes[0];
  const firstFailure = graph.nodes.find((n) => n.error_code) ?? null;
  const [selected, setSelected] = useState<string | null>(root?.id ?? null);
  const findingsBySpan = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const f of findings) for (const s of f.evidence_span_ids) counts[s] = (counts[s] ?? 0) + 1;
    return counts;
  }, [findings]);
  const eventSpan = useMemo(
    () => Object.fromEntries(timeline.events.map((e) => [e.event_id, e.span_id])),
    [timeline],
  );
  const intervened = useMemo(
    () => timeline.events.filter((e) => e.attributes.intervention && e.span_id).map((e) => e.span_id as string),
    [timeline],
  );

  return (
    <>
      <Header detail={detail} onJump={firstFailure ? () => setSelected(firstFailure.id) : undefined} />
      <Lineage detail={detail} replays={replays} />
      <FindingsPanel findings={findings} eventSpan={eventSpan} onSelect={setSelected} />
      <div className="mt-4 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)_400px]">
        <TimelinePanel events={timeline.events} selected={selected} onSelect={setSelected} />
        <Card title="Execution graph" className="min-w-0">
          <ExecutionGraph graph={graph} selected={selected} onSelect={setSelected}
            findingsBySpan={findingsBySpan} intervenedSpans={intervened} />
        </Card>
        <SpanPanel timeline={timeline} spanId={selected} findings={findings} />
      </div>
    </>
  );
}

const SEVERITY: Record<string, string> = {
  critical: "bg-bad text-ink", high: "bg-bad/20 text-bad", medium: "bg-warn/20 text-warn", low: "bg-line text-muted",
};

function FindingsPanel({ findings, eventSpan, onSelect }: {
  findings: Finding[]; eventSpan: Record<string, string | null>; onSelect: (span: string) => void;
}) {
  return (
    <Card title={`Findings · ${findings.length}`} className="mt-4">
      {findings.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted" data-testid="no-findings">
          No detector fired on this run. That is not proof the run is healthy: only the five
          rule-based detectors (schema mismatch, retry loop, timeout, budget, identity) were applied.
        </p>
      ) : (
        <ul className="divide-y divide-line" data-testid="findings">
          {findings.map((f) => (
            <li key={f.id} className="px-4 py-3" data-testid="finding" data-category={f.category}>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${SEVERITY[f.severity] ?? SEVERITY.low}`}>{f.severity}</span>
                <span className="font-mono text-xs text-muted">{f.category}</span>
                <span className="text-sm font-medium">{f.title}</span>
                <span className="ml-auto rounded border border-ok/40 px-1.5 py-0.5 text-[10px] text-ok"
                  title="Produced by a deterministic detector from recorded events">
                  verified · {f.detector} v{f.detector_version}
                </span>
              </div>
              <p className="mt-1 text-sm text-muted">{f.explanation}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-muted">Evidence:</span>
                {f.evidence_event_ids.map((id) => (
                  <button key={id} type="button" disabled={!eventSpan[id]}
                    onClick={() => eventSpan[id] && onSelect(eventSpan[id] as string)}
                    className="rounded border border-line px-1.5 py-0.5 font-mono hover:bg-line focus-visible:outline-2 focus-visible:outline-ok">
                    event {shortId(id, 6)}
                  </button>
                ))}
              </div>
              {f.caveats.length > 0 && <p className="mt-1 text-[11px] text-muted">Caveats: {f.caveats.join("; ")}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Lineage({ detail, replays }: { detail: ExecutionDetail; replays: ReplayJob[] }) {
  const replay = (detail.attributes as Record<string, unknown>).replay as
    | { job_id?: string; checkpoint_step_index?: number }
    | undefined;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
      <a href={href(`/runs/${detail.id}/replay`)} data-testid="open-replay-studio"
        className="rounded border border-warn/60 px-3 py-1.5 text-warn hover:bg-warn/10 focus-visible:outline-2 focus-visible:outline-warn">
        ⑂ Replay Studio
      </a>
      {detail.parent_execution_id && (
        <span className="text-muted">
          Fork of <a className="font-mono text-[#e6edf3] hover:underline" href={href(`/runs/${detail.parent_execution_id}`)}>{shortId(detail.parent_execution_id)}</a>
          {replay?.checkpoint_step_index !== undefined && <> from checkpoint before call #{replay.checkpoint_step_index}</>}
          {replay?.job_id && <> · <a className="hover:underline" href={href(`/replays/${replay.job_id}`)}>comparison →</a></>}
        </span>
      )}
      {replays.length > 0 && (
        <span className="text-muted">
          Replays of this run:{" "}
          {replays.map((r) => (
            <a key={r.job_id} href={href(`/replays/${r.job_id}`)} className="mr-2 font-mono hover:underline">
              {shortId(r.job_id, 6)}<span className={r.result.fork_verifier_passed ? "text-ok" : "text-bad"}> {String(r.status)}</span>
            </a>
          ))}
        </span>
      )}
    </div>
  );
}

function Header({ detail, onJump }: { detail: ExecutionDetail; onJump?: () => void }) {
  const a = detail.attributes as Record<string, unknown>;
  const verifier = a.verifier as { passed?: boolean; reasons?: string[] } | undefined;
  const fixture = a.fixture as { id: string; version: string; sha256: string } | undefined;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4 px-4 py-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-lg font-semibold">{detail.task_id}</h1>
            <StatusBadge status={detail.status} />
            {detail.error_codes.map((c) => <Tag key={c}>{c}</Tag>)}
          </div>
          <p className="mt-1 font-mono text-xs text-muted">run {detail.id}</p>
        </div>
        {onJump && (
          <button type="button" onClick={onJump}
            className="rounded border border-bad/50 px-3 py-1.5 text-sm text-bad hover:bg-bad/10 focus-visible:outline-2 focus-visible:outline-bad">
            Jump to first failure
          </button>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line px-4 py-3 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <Field label="Verifier">
          {verifier?.passed === undefined ? "—" : (
            <span className={verifier.passed ? "text-ok" : "text-bad"}>{verifier.passed ? "passed" : "failed"}</span>
          )}
          {verifier?.reasons && verifier.reasons.length > 0 && (
            <span className="block text-xs text-muted">{verifier.reasons.join(", ")}</span>
          )}
        </Field>
        <Field label="Termination">{detail.termination ?? "—"}</Field>
        <Field label="Duration">{fmtDuration(detail.duration_ms)}</Field>
        <Field label="Tool calls">{detail.tool_calls}</Field>
        <Field label="Agent version">
          {detail.agent_version.agent} @ {detail.agent_version.git_sha.slice(0, 7)}
          <span className="block text-xs text-muted">{detail.agent_version.model_name} · {String(a.determinism ?? "")}</span>
        </Field>
        <Field label="Started">{fmtTime(detail.started_at)}</Field>
        <Field label="Fixture">
          {fixture ? <>{fixture.id}@{fixture.version}<span className="block text-xs text-muted">sha256 {fixture.sha256.slice(0, 12)}…</span></> : "—"}
        </Field>
        <Field label="Capture">{String(a.capture_policy ?? "—")}</Field>
        <Field label="Recorded">{detail.span_count} spans · {detail.event_count} events</Field>
      </dl>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-0.5 break-words font-mono text-xs">{children}</dd>
    </div>
  );
}

// ------------------------------------------------------------------ timeline
function TimelinePanel({ events, selected, onSelect }: {
  events: EventOut[]; selected: string | null; onSelect: (id: string) => void;
}) {
  return (
    <Card title={`Timeline · ${events.length} events`} className="lg:max-h-[640px] lg:overflow-y-auto">
      <ol className="divide-y divide-line">
        {events.map((e) => {
          const active = e.span_id !== null && e.span_id === selected;
          const code = typeof e.payload.error_code === "string" ? e.payload.error_code : null;
          return (
            <li key={e.event_id}>
              <button
                type="button"
                disabled={!e.span_id}
                onClick={() => e.span_id && onSelect(e.span_id)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-line/50 focus-visible:bg-line focus-visible:outline-none ${active ? "bg-line" : ""}`}
              >
                <span className="w-6 shrink-0 text-right font-mono text-muted">{e.sequence_no}</span>
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${e.status === "error" ? "bg-bad" : e.status === "ok" ? "bg-ok" : "bg-muted"}`} aria-hidden />
                <span className="min-w-0 break-words">
                  <span className="font-mono">{e.event_type}</span>
                  {e.tool_name && <span className="ml-1 font-mono text-muted">{e.tool_name}</span>}
                  {code && <span className="ml-1 font-mono text-bad">{code}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

// ------------------------------------------------------------------ span inspector
function SpanPanel({ timeline, spanId, findings }: { timeline: Timeline; spanId: string | null; findings: Finding[] }) {
  const span = timeline.spans.find((s) => s.span_id === spanId) ?? null;
  const cited = findings.filter((f) => spanId && f.evidence_span_ids.includes(spanId));
  const events = timeline.events.filter((e) => e.span_id === spanId);
  const failure = events.find((e) => e.status === "error");
  return (
    <Card title="Span inspector" className="lg:max-h-[640px] lg:overflow-y-auto">
      {!span ? (
        <p className="px-4 py-6 text-sm text-muted">Select a node or a timeline event.</p>
      ) : (
        <div className="space-y-4 px-4 py-3 text-sm" data-testid="span-inspector">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold">{span.name}</span>
              <StatusBadge status={span.status} />
            </div>
            <p className="mt-1 font-mono text-[11px] text-muted">
              span {span.span_id} · parent {span.parent_span_id ?? "—"} · {span.kind} · {fmtDuration(span.duration_ms)}
            </p>
          </div>

          {cited.length > 0 && (
            <div className="rounded-md border border-line px-3 py-2" data-testid="span-findings">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted">Cited by findings</p>
              <ul className="mt-1 space-y-0.5 text-xs">
                {cited.map((f) => <li key={f.id}><span className="font-mono text-bad">{f.category}</span> · {f.title}</li>)}
              </ul>
            </div>
          )}

          {failure && (
            <div role="alert" className="rounded-md border border-bad/40 bg-bad/10 px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-bad">Error</p>
              <p className="mt-1 font-mono text-sm text-bad" data-testid="error-code">{String(failure.payload.error_code ?? "error")}</p>
              {typeof failure.payload.error_message === "string" && (
                <p className="mt-1 font-mono text-xs text-muted">{failure.payload.error_message}</p>
              )}
              {typeof failure.attributes.error_type === "string" && (
                <p className="mt-1 text-xs text-muted">type: {failure.attributes.error_type}</p>
              )}
            </div>
          )}

          <div>
            <p className="mb-1 text-xs uppercase tracking-wider text-muted">Attributes</p>
            <JsonBlock value={span.attributes} />
          </div>

          {events.map((e) => (
            <div key={e.event_id}>
              <p className="mb-1 flex items-center gap-2 text-xs text-muted">
                <span className="font-mono">#{e.sequence_no} {e.event_type}</span>
                {e.status && <StatusBadge status={e.status} />}
                <span className="ml-auto">{new Date(e.timestamp).toLocaleTimeString()}</span>
              </p>
              <JsonBlock value={{ ...e.payload, ...(Object.keys(e.attributes).length ? { attributes: e.attributes } : {}) }} />
            </div>
          ))}
          <p className="text-[11px] text-muted">
            Payloads are shown as stored: redacted server-side; values appear only when the run
            was recorded with content capture enabled.
          </p>
        </div>
      )}
    </Card>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded bg-ink px-3 py-2 font-mono text-[11px] leading-5 text-[#c9d1d9]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

