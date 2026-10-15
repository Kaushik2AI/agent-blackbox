"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  type Edge,
} from "@xyflow/react";
import { useMemo, useState } from "react";
import { api, type EventOut, type ExecutionDetail, type Graph, type Timeline } from "@/lib/api";
import { fmtDuration, fmtTime, href } from "@/lib/format";
import { layoutGraph } from "@/lib/graph-layout";
import { useApi } from "@/lib/use-api";
import { Card, ErrorBox, Loading, StatusBadge, Tag } from "./ui";

type Loaded = { detail: ExecutionDetail; timeline: Timeline; graph: Graph };

async function loadAll(id: string): Promise<Loaded> {
  const [detail, timeline, graph] = await Promise.all([api.execution(id), api.timeline(id), api.graph(id)]);
  return { detail, timeline, graph };
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
  const { detail, timeline, graph } = data;
  const root = graph.nodes.find((n) => n.parent_span_id === null) ?? graph.nodes[0];
  const firstFailure = graph.nodes.find((n) => n.error_code) ?? null;
  const [selected, setSelected] = useState<string | null>(root?.id ?? null);

  return (
    <>
      <Header detail={detail} onJump={firstFailure ? () => setSelected(firstFailure.id) : undefined} />
      <div className="mt-4 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)_400px]">
        <TimelinePanel events={timeline.events} selected={selected} onSelect={setSelected} />
        <GraphPanel graph={graph} selected={selected} onSelect={setSelected} />
        <SpanPanel timeline={timeline} spanId={selected} />
      </div>
    </>
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

// ------------------------------------------------------------------ graph
type SpanNodeData = {
  label: string; kind: string; status: string; error: string | null;
  duration: number | null; selected: boolean; orphan: boolean;
};

function SpanNode({ data }: NodeProps<Node<SpanNodeData>>) {
  const tone = data.status === "error" ? "border-bad" : data.status === "ok" ? "border-ok/60" : "border-line";
  return (
    <div
      data-testid="graph-node"
      data-status={data.status}
      data-error={data.error ?? ""}
      className={`w-[230px] rounded-md border bg-panel px-3 py-2 text-left shadow ${tone} ${data.selected ? "ring-2 ring-[#e6edf3]" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-line" />
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">{data.kind}{data.orphan ? " · orphan" : ""}</span>
        <span className="font-mono text-[10px] text-muted">{fmtDuration(data.duration)}</span>
      </div>
      <div className="truncate font-mono text-xs text-[#e6edf3]">{data.label}</div>
      {data.error && <div className="mt-1 font-mono text-[11px] text-bad">{data.error}</div>}
      <Handle type="source" position={Position.Bottom} className="!bg-line" />
    </div>
  );
}

const NODE_TYPES = { span: SpanNode };

function GraphPanel({ graph, selected, onSelect }: {
  graph: Graph; selected: string | null; onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const layout = layoutGraph(graph.nodes, graph.edges);
    const nodes: Node<SpanNodeData>[] = layout.positioned.map((p) => ({
      id: p.node.id,
      type: "span",
      position: { x: p.x, y: p.y },
      ariaLabel: `${p.node.name}, ${p.node.status}${p.node.error_code ? `, ${p.node.error_code}` : ""}`,
      data: {
        label: p.node.name, kind: p.node.kind, status: p.node.status, error: p.node.error_code,
        duration: p.node.duration_ms, selected: p.node.id === selected, orphan: p.node.orphan,
      },
    }));
    const edges: Edge[] = layout.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target,
      style: { stroke: e.failed ? "#f85149" : "#3d4651", strokeWidth: 1.5 },
    }));
    return { nodes, edges };
  }, [graph, selected]);

  return (
    <Card title="Execution graph" className="min-w-0">
      <div className="h-[520px] lg:h-[600px]" data-testid="graph">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodeClick={(_, n) => onSelect(n.id)}
          nodesDraggable={false}
          nodesConnectable={false}
          colorMode="dark"
          fitView
          // Fit the first steps so labels stay readable; scroll/drag to see the rest.
          fitViewOptions={{ padding: 0.1, maxZoom: 1, nodes: nodes.slice(0, 9).map((n) => ({ id: n.id })) }}
          panOnScroll
          minZoom={0.2}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} color="#232a33" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ span inspector
function SpanPanel({ timeline, spanId }: { timeline: Timeline; spanId: string | null }) {
  const span = timeline.spans.find((s) => s.span_id === spanId) ?? null;
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

