import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../lib/api";
import { LANE, layoutGraph } from "../lib/graph-layout";

const node = (id: string, kind: string, order: number, extra: Partial<GraphNode> = {}): GraphNode => ({
  id, kind, name: id, status: "ok", order, parent_span_id: kind === "agent" ? null : "root",
  orphan: false, duration_ms: 1, tool_name: null, error_code: null, ...extra,
});

describe("layoutGraph", () => {
  const nodes = [
    node("root", "agent", 0),
    node("m1", "llm", 1),
    node("t1", "tool", 2, { status: "error" }),
    node("m2", "llm", 3),
  ];
  const edges: GraphEdge[] = [
    { id: "n1", source: "m1", target: "t1", kind: "next" },
    { id: "n2", source: "t1", target: "m2", kind: "next" },
    { id: "p1", source: "root", target: "m1", kind: "parent" },
  ];

  it("puts model calls and tool calls in separate lanes, in start order", () => {
    const { positioned } = layoutGraph(nodes, edges);
    const pos = Object.fromEntries(positioned.map((p) => [p.node.id, p]));
    expect(pos.root.y).toBe(0);
    expect(pos.m1.x).toBe(LANE.llm);
    expect(pos.t1.x).toBe(LANE.tool);
    expect(pos.m1.y).toBeLessThan(pos.t1.y);
    expect(pos.t1.y).toBeLessThan(pos.m2.y);
  });

  it("draws control-flow edges, marks edges leaving failed spans, links root to first step", () => {
    const { edges: out } = layoutGraph(nodes, edges);
    expect(out.map((e) => e.id)).toEqual(["root-m1", "n1", "n2"]);
    expect(out.find((e) => e.id === "n2")?.failed).toBe(true);
  });

  it("keeps orphans visible in their own lane", () => {
    const { positioned } = layoutGraph([...nodes, node("lost", "tool", 4, { orphan: true, parent_span_id: "gone" })], edges);
    expect(positioned.find((p) => p.node.id === "lost")?.x).toBe(LANE.orphan);
  });
});
