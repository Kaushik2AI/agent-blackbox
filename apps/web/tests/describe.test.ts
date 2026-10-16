import { describe, expect, it } from "vitest";
import type { EventOut, LiveStep } from "../lib/api";
import { describeStep, fmtClock, toolTitle, verdict } from "../lib/describe";
import { fromLive, fromTimeline } from "../lib/steps";

const tool = (over: Partial<Extract<LiveStep, { kind: "tool" }>>): LiveStep => ({
  kind: "tool",
  call_index: 0,
  tool: "lookup_inventory",
  args: { sku: "SKU-RED-004" },
  ok: true,
  result: { sku: "SKU-RED-004", available: true, quantity: 12, as_of: "x" },
  error_code: null,
  error: null,
  intervention: null,
  t_ms: 1200,
  ...over,
});

describe("plain-language steps", () => {
  it("names tool calls by what they do", () => {
    expect(toolTitle("lookup_order", { order_id: "ORD-1001" })).toBe("Look up order ORD-1001");
    expect(toolTitle("lookup_inventory", { product_name: "red backpack" })).toBe("Check stock for “red backpack”");
    expect(toolTitle("submit_resolution", { order_id: "ORD-1", choice: "refund" })).toBe("Close the ticket: refund for ORD-1");
  });

  it("hides shape placeholders from metadata-only runs", () => {
    expect(toolTitle("lookup_order", { order_id: "<str len=8>" })).toBe("Look up the order");
  });

  it("explains errors and successes", () => {
    const [ok] = fromLive([tool({})]);
    expect(describeStep(ok)).toMatchObject({ tone: "ok", detail: "In stock: 12" });
    const [bad] = fromLive([tool({ ok: false, result: null, args: { product_name: "x" }, error_code: "SKU_REQUIRED" })]);
    expect(describeStep(bad).tone).toBe("bad");
    expect(describeStep(bad).detail).toContain("product code");
    const [slow] = fromLive([tool({ ok: false, result: null, error_code: "TIMEOUT" })]);
    expect(describeStep(slow).tone).toBe("warn");
  });

  it("attaches the AI's note and tokens to the following tool step", () => {
    const steps = fromLive([
      { kind: "decision", action: "tool_call", tool: "lookup_inventory", args: {}, reason: null, note: "check stock",
        tokens: { input_tokens: 90, output_tokens: 10 }, unparsed: false, t_ms: 900 },
      tool({}),
      { kind: "decision", action: "finish", tool: null, args: null, reason: "completed", note: "all done", tokens: null, unparsed: false, t_ms: 2000 },
      { kind: "end", termination: "completed", verifier_passed: true, t_ms: 2001 },
    ]);
    expect(steps).toHaveLength(2);
    expect(steps[0]).toMatchObject({ kind: "tool", note: "check stock", tokens: 100 });
    expect(describeStep(steps[1]).title).toBe("Agent says it's done");
  });

  it("builds the same steps from stored timeline events", () => {
    const ev = (seq: number, type: string, extra: Partial<EventOut>): EventOut => ({
      event_id: `e${seq}`, span_id: `s${seq}`, sequence_no: seq, event_type: type,
      timestamp: new Date(1_000 + seq * 500).toISOString(), operation: null, tool_name: null,
      status: "ok", attributes: {}, payload: {}, ...extra,
    });
    const steps = fromTimeline([
      ev(2, "tool_call_end", { tool_name: "lookup_inventory", status: "error", attributes: { call_index: 1 },
        payload: { capture: "content", input_redacted: { product_name: "bag" }, error_code: "SKU_REQUIRED" } }),
      ev(1, "llm_call_end", { payload: { action: "tool_call", note: "check" }, attributes: { "gen_ai.usage.input_tokens": 5, "gen_ai.usage.output_tokens": 1 } }),
      ev(3, "budget_exhausted", { payload: { max_tool_calls: 8 } }),
    ]);
    expect(steps.map((s) => s.kind)).toEqual(["tool", "budget"]);
    expect(steps[0]).toMatchObject({ callIndex: 1, errorCode: "SKU_REQUIRED", note: "check", tokens: 6, spanId: "s2", tMs: 500 });
    expect(describeStep(steps[1]).title).toBe("Stopped: all 8 allowed steps used");
  });
});

describe("verdicts", () => {
  it("explains the flagship failure", () => {
    const v = verdict({ passed: false, termination: "budget_exhausted", categories: ["tool_schema_mismatch", "retry_loop", "budget_exhausted"] });
    expect(v.headline).toBe("Failed");
    expect(v.line).toContain("kept repeating");
  });
  it("prefers the identity explanation and handles passes", () => {
    expect(verdict({ passed: false, categories: ["state_identity_mismatch"] }).line).toContain("different order");
    expect(verdict({ passed: true }).headline).toBe("Solved");
    expect(verdict({ passed: false, reasons: ["wrong_resolution: x"] }).line).toContain("wrong decision");
  });
  it("formats clock times", () => {
    expect(fmtClock(0)).toBe("00:00.0");
    expect(fmtClock(61_500)).toBe("01:01.5");
  });
});
