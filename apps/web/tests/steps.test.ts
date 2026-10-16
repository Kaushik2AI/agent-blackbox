import { describe, expect, it } from "vitest";
import { findRepeats, type TapeStep } from "../lib/steps";

function call(i: number, args: Record<string, unknown>, ok = false, code: string | null = "SKU_REQUIRED"): TapeStep {
  return {
    kind: "tool", key: `t${i}`, callIndex: i, tool: "lookup_inventory", args, ok,
    result: null, errorCode: ok ? null : code, error: null, note: null, tokens: null,
    tMs: null, intervention: null, spanId: null,
  };
}

describe("findRepeats", () => {
  it("folds 3+ identical failing steps into the first one", () => {
    const bad = { product_name: "red backpack" };
    const steps = [call(0, { order_id: "x" }, true), call(1, bad), call(2, bad), call(3, bad), call(4, bad)];
    expect(findRepeats(steps)).toEqual(new Map([["t1", ["t2", "t3", "t4"]]]));
  });
  it("leaves short or different sequences alone", () => {
    expect(findRepeats([call(0, { a: 1 }), call(1, { a: 1 })]).size).toBe(0);
    expect(findRepeats([call(0, { a: 1 }), call(1, { a: 2 }), call(2, { a: 1 })]).size).toBe(0);
    expect(findRepeats([call(0, { a: 1 }, true), call(1, { a: 1 }, true), call(2, { a: 1 }, true)]).size).toBe(0);
  });
});
