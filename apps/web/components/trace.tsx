"use client";

import type { EventOut, Finding, Graph, Timeline } from "@/lib/api";
import { fmtDuration } from "@/lib/format";
import { ExecutionGraph } from "./execution-graph";
import { Card, JsonBlock, StatusBadge } from "./ui";

function countBySpan(findings: Finding[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const f of findings) for (const s of f.evidence_span_ids) counts[s] = (counts[s] ?? 0) + 1;
  return counts;
}

export function intervenedSpans(events: EventOut[]): string[] {
  return events.filter((e) => e.attributes.intervention && e.span_id).map((e) => e.span_id as string);
}

/** Technical trace: every stored event, the span graph and the raw payload of a span. */
export function TraceTab({ timeline, graph, findings, selected, onSelect }: {
  timeline: Timeline; graph: Graph; findings: Finding[]; selected: string | null; onSelect: (id: string) => void;
}) {
  return (
    <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)_400px]" data-testid="trace">
      <EventLog events={timeline.events} selected={selected} onSelect={onSelect} />
      <Card title="Span graph" className="min-w-0">
        <ExecutionGraph graph={graph} selected={selected} onSelect={onSelect}
          findingsBySpan={countBySpan(findings)} intervenedSpans={intervenedSpans(timeline.events)} height="h-[560px]" />
      </Card>
      <SpanInspector timeline={timeline} spanId={selected} findings={findings} />
    </div>
  );
}

function EventLog({ events, selected, onSelect }: { events: EventOut[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <Card title={`Events (${events.length})`} className="lg:max-h-[620px] lg:overflow-y-auto">
      <ol className="divide-y divide-line">
        {events.map((e) => {
          const active = e.span_id !== null && e.span_id === selected;
          const code = typeof e.payload.error_code === "string" ? e.payload.error_code : null;
          return (
            <li key={e.event_id}>
              <button type="button" disabled={!e.span_id} onClick={() => e.span_id && onSelect(e.span_id)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-canvas focus-visible:bg-canvas focus-visible:outline-none ${active ? "bg-context-tint" : ""}`}>
                <span className="num w-6 shrink-0 text-right text-fg-3">{e.sequence_no}</span>
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${e.status === "error" ? "bg-bad" : e.status === "ok" ? "bg-ok" : "bg-fg-3"}`} aria-hidden />
                <span className="min-w-0 break-words">
                  <span className="font-mono">{e.event_type}</span>
                  {e.tool_name && <span className="ml-1 font-mono text-fg-2">{e.tool_name}</span>}
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

function SpanInspector({ timeline, spanId, findings }: { timeline: Timeline; spanId: string | null; findings: Finding[] }) {
  const span = timeline.spans.find((s) => s.span_id === spanId) ?? null;
  const cited = findings.filter((f) => spanId && f.evidence_span_ids.includes(spanId));
  const events = timeline.events.filter((e) => e.span_id === spanId);
  const failure = events.find((e) => e.status === "error");
  return (
    <Card title="Selected span" className="lg:max-h-[620px] lg:overflow-y-auto">
      {!span ? (
        <p className="px-4 py-6 text-sm text-fg-2">Select a node in the graph or an event in the list.</p>
      ) : (
        <div className="space-y-4 px-4 py-3 text-sm" data-testid="span-inspector">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold">{span.name}</span>
              <StatusBadge status={span.status} />
            </div>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-[11.5px] text-fg-2">
              <dt>span</dt><dd>{span.span_id}</dd>
              <dt>parent</dt><dd>{span.parent_span_id ?? "none"}</dd>
              <dt>kind</dt><dd>{span.kind}</dd>
              <dt>duration</dt><dd>{fmtDuration(span.duration_ms)}</dd>
            </dl>
          </div>
          {cited.length > 0 && (
            <div className="rounded-[8px] bg-bad-tint/60 px-3 py-2" data-testid="span-findings">
              <p className="text-[13px] font-medium text-bad">Cited by findings</p>
              <ul className="mt-1 space-y-0.5 text-xs">
                {cited.map((f) => <li key={f.id}><span className="font-mono text-bad">{f.category}</span> {f.title}</li>)}
              </ul>
            </div>
          )}
          {failure && (
            <div role="alert" className="rounded-[8px] bg-bad-tint px-3 py-2">
              <p className="text-[13px] font-medium text-bad">Error</p>
              <p className="mt-1 font-mono text-sm text-bad" data-testid="error-code">{String(failure.payload.error_code ?? "error")}</p>
              {typeof failure.payload.error_message === "string" && <p className="mt-1 font-mono text-xs text-fg-2">{failure.payload.error_message}</p>}
              {typeof failure.attributes.error_type === "string" && <p className="mt-1 text-xs text-fg-2">type: {failure.attributes.error_type}</p>}
            </div>
          )}
          <div>
            <p className="mb-1 text-[13px] text-fg-2">Attributes</p>
            <JsonBlock value={span.attributes} />
          </div>
          {events.map((e) => (
            <div key={e.event_id}>
              <p className="mb-1 flex items-center gap-2 text-xs text-fg-2">
                <span className="font-mono">#{e.sequence_no} {e.event_type}</span>
                {e.status && <StatusBadge status={e.status} />}
                <span className="ml-auto">{new Date(e.timestamp).toLocaleTimeString()}</span>
              </p>
              <JsonBlock value={{ ...e.payload, ...(Object.keys(e.attributes).length ? { attributes: e.attributes } : {}) }} />
            </div>
          ))}
          <p className="text-[11.5px] text-fg-3">
            Payloads are shown as stored: redacted on the server, with values only when the run was recorded with content capture.
          </p>
        </div>
      )}
    </Card>
  );
}
