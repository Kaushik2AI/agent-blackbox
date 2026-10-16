import { describe, expect, it } from "vitest";
import type { Finding } from "../lib/api";
import type { TapeStep } from "../lib/steps";
import { buildBeats, narrate, rootCause } from "../lib/story";

function call(i: number, tool: string, args: Record<string, unknown>, ok = true, code: string | null = null, result: Record<string, unknown> | null = null): TapeStep {
  return { kind: "tool", key: `t${i}`, callIndex: i, tool, args, ok, result, errorCode: code, error: null, note: null, tokens: null, tMs: null, intervention: null, spanId: `s${i}` };
}

const bad = { product_name: "red backpack" };
const flagship: TapeStep[] = [
  call(0, "lookup_order", { order_id: "ORD-1001" }, true, null, { product_name: "red backpack", sku: "SKU-RED-004" }),
  ...[1, 2, 3, 4, 5, 6, 7].map((i) => call(i, "lookup_inventory", bad, false, "SKU_REQUIRED")),
  { kind: "budget", key: "b", max: 8, tMs: null },
];

function finding(category: string, spans: string[]): Finding {
  return { id: category, category, severity: "high", title: category, explanation: "x", evidence_event_ids: [], evidence_span_ids: spans, caveats: [], detector: category, detector_version: "1", kind: "verified" };
}

describe("story", () => {
  it("keeps the first failing step as a waypoint and folds its repeats into one loop", () => {
    const beats = buildBeats(flagship);
    expect(beats.map((b) => b.kind)).toEqual(["step", "step", "loop", "end"]);
    const loop = beats[2];
    expect(loop.kind === "loop" && loop.repeats.length).toBe(6);
    // Unfolding shows every attempt again.
    expect(buildBeats(flagship, { fold: true, unfold: new Set(["t1"]) }).filter((b) => b.kind === "step")).toHaveLength(8);
  });

  it("ranks the wrong input as the cause and the loop and budget as symptoms", () => {
    const fs = [finding("budget_exhausted", []), finding("retry_loop", ["s1", "s2"]), finding("tool_schema_mismatch", ["s1"])];
    const c = rootCause(fs, flagship, { passed: false, termination: "budget_exhausted" });
    expect(c?.title).toBe("Wrong input to the stock check");
    expect(c?.step?.callIndex).toBe(1);
    expect(c?.symptoms.map((s) => s.category)).toEqual(["retry_loop", "budget_exhausted"]);
  });

  it("tells the story in plain words", () => {
    const c = rootCause([finding("tool_schema_mismatch", ["s1"])], flagship, { passed: false });
    const text = narrate(flagship, { passed: false, termination: "budget_exhausted", fallback: "x" }, c);
    expect(text).toContain("looked up order ORD-1001");
    expect(text).toContain("6 more times");
    expect(text).toContain("all 8 of its steps");
  });

  it("names the mixed-up orders", () => {
    const steps: TapeStep[] = [
      call(0, "lookup_order", { order_id: "ORD-1001" }),
      call(1, "submit_resolution", { order_id: "ORD-1002", choice: "exchange" }),
    ];
    const c = rootCause([finding("state_identity_mismatch", [])], steps, { passed: false });
    expect(narrate(steps, { passed: false, fallback: "x" }, c)).toContain("closed the ticket for order ORD-1002");
  });
});
