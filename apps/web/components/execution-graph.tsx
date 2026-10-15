"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  type Edge,
  Handle,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { useMemo } from "react";
import type { Graph } from "@/lib/api";
import { fmtDuration } from "@/lib/format";
import { layoutGraph } from "@/lib/graph-layout";

type SpanNodeData = {
  label: string;
  kind: string;
  status: string;
  error: string | null;
  duration: number | null;
  selected: boolean;
  orphan: boolean;
  findings: number;
  intervened: boolean;
};

function SpanNode({ data }: NodeProps<Node<SpanNodeData>>) {
  const tone = data.status === "error" ? "border-bad" : data.status === "ok" ? "border-ok/60" : "border-line";
  return (
    <div
      data-testid="graph-node"
      data-status={data.status}
      data-error={data.error ?? ""}
      className={`w-[230px] rounded-md border bg-panel px-3 py-2 text-left shadow ${tone} ${data.selected ? "ring-2 ring-[#e6edf3]" : ""} ${data.intervened ? "outline outline-2 outline-offset-2 outline-warn" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-line" />
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
          {data.kind}{data.orphan ? " · orphan" : ""}{data.intervened ? " · intervened" : ""}
        </span>
        <span className="flex items-center gap-1.5">
          {data.findings > 0 && (
            <span title={`${data.findings} finding(s) cite this step`}
              className="rounded bg-bad/20 px-1 font-mono text-[10px] text-bad">⚑{data.findings}</span>
          )}
          <span className="font-mono text-[10px] text-muted">{fmtDuration(data.duration)}</span>
        </span>
      </div>
      <div className="truncate font-mono text-xs text-[#e6edf3]">{data.label}</div>
      {data.error && <div className="mt-1 font-mono text-[11px] text-bad">{data.error}</div>}
      <Handle type="source" position={Position.Bottom} className="!bg-line" />
    </div>
  );
}

const NODE_TYPES = { span: SpanNode };

export function ExecutionGraph({
  graph,
  selected,
  onSelect,
  findingsBySpan = {},
  intervenedSpans = [],
  height = "h-[520px] lg:h-[600px]",
  testId = "graph",
}: {
  graph: Graph;
  selected: string | null;
  onSelect: (id: string) => void;
  findingsBySpan?: Record<string, number>;
  intervenedSpans?: string[];
  height?: string;
  testId?: string;
}) {
  const { nodes, edges } = useMemo(() => {
    const layout = layoutGraph(graph.nodes, graph.edges);
    const nodes: Node<SpanNodeData>[] = layout.positioned.map((p) => ({
      id: p.node.id,
      type: "span",
      position: { x: p.x, y: p.y },
      ariaLabel: `${p.node.name}, ${p.node.status}${p.node.error_code ? `, ${p.node.error_code}` : ""}`,
      data: {
        label: p.node.name,
        kind: p.node.kind,
        status: p.node.status,
        error: p.node.error_code,
        duration: p.node.duration_ms,
        selected: p.node.id === selected,
        orphan: p.node.orphan,
        findings: findingsBySpan[p.node.id] ?? 0,
        intervened: intervenedSpans.includes(p.node.id),
      },
    }));
    const edges: Edge[] = layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      style: { stroke: e.failed ? "#f85149" : "#3d4651", strokeWidth: 1.5 },
    }));
    return { nodes, edges };
  }, [graph, selected, findingsBySpan, intervenedSpans]);

  return (
    <div className={height} data-testid={testId}>
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
  );
}
