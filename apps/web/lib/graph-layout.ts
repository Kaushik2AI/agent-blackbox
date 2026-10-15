/**
 * Pure layout for the execution graph (unit-tested). Two lanes under the agent root:
 * model decisions on the left, tool calls on the right, in the order they started.
 * Spans whose parent never arrived ("orphans") get their own lane so they stay visible.
 */
import type { GraphEdge, GraphNode } from "./api";

export type Positioned = { node: GraphNode; x: number; y: number };
export type LayoutEdge = { id: string; source: string; target: string; failed: boolean };

export const LANE = { llm: 0, tool: 300, other: 150, orphan: 600 } as const;
const ROW = 80;

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]) {
  const sorted = [...nodes].sort((a, b) => a.order - b.order);
  const root = sorted.find((n) => n.parent_span_id === null && n.kind === "agent") ?? null;
  const positioned: Positioned[] = [];
  let row = 0;
  if (root) positioned.push({ node: root, x: LANE.other, y: 0 });
  for (const n of sorted) {
    if (n === root) continue;
    const x = n.orphan
      ? LANE.orphan
      : n.kind === "llm" ? LANE.llm : n.kind === "tool" ? LANE.tool : LANE.other;
    positioned.push({ node: n, x, y: 110 + row * ROW });
    row += 1;
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const flow: LayoutEdge[] = edges
    .filter((e) => e.kind === "next")
    .map((e) => ({ id: e.id, source: e.source, target: e.target,
      failed: byId.get(e.source)?.status === "error" }));
  const firstChild = positioned.find((p) => p.node !== root && !p.node.orphan);
  if (root && firstChild) {
    flow.unshift({ id: `root-${firstChild.node.id}`, source: root.id, target: firstChild.node.id, failed: false });
  }
  return { positioned, edges: flow };
}
