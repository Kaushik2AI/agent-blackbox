/**
 * One shape for "what the agent did", whether it comes from a live run (streamed records)
 * or from a stored run (timeline events). The tape component renders these.
 */
import type { EventOut, LiveStep } from "./api";

export type TapeStep =
  | {
      kind: "tool";
      key: string;
      callIndex: number;
      tool: string;
      args: Record<string, unknown>;
      ok: boolean;
      result: Record<string, unknown> | null;
      errorCode: string | null;
      error: string | null;
      note: string | null;
      tokens: number | null;
      tMs: number | null;
      intervention: string | null;
      spanId: string | null;
    }
  | { kind: "finish"; key: string; reason: string; note: string | null; unreadable: boolean; tMs: number | null }
  | { kind: "budget"; key: string; max: number | null; tMs: number | null };

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export function fromLive(steps: LiveStep[]): TapeStep[] {
  const out: TapeStep[] = [];
  let note: string | null = null;
  let tokens: number | null = null;
  steps.forEach((s, i) => {
    if (s.kind === "decision") {
      if (s.action === "finish") {
        out.push({ kind: "finish", key: `f${i}`, reason: s.reason ?? "completed", note: s.note, unreadable: s.unparsed, tMs: s.t_ms });
        note = null;
      } else {
        note = s.note;
        tokens = s.tokens ? s.tokens.input_tokens + s.tokens.output_tokens : null;
      }
    } else if (s.kind === "tool") {
      out.push({
        kind: "tool",
        key: `t${s.call_index}`,
        callIndex: s.call_index,
        tool: s.tool,
        args: s.args,
        ok: s.ok,
        result: s.result,
        errorCode: s.error_code,
        error: s.error,
        note,
        tokens,
        tMs: s.t_ms,
        intervention: s.intervention,
        spanId: null,
      });
      note = null;
      tokens = null;
    } else if (s.kind === "budget") {
      out.push({ kind: "budget", key: `b${i}`, max: s.max_tool_calls, tMs: s.t_ms });
    }
  });
  return out;
}

export function fromTimeline(events: EventOut[]): TapeStep[] {
  const sorted = [...events].sort((a, b) => a.sequence_no - b.sequence_no);
  const t0 = sorted.length ? Date.parse(sorted[0].timestamp) : 0;
  const at = (e: EventOut) => Math.max(0, Date.parse(e.timestamp) - t0);
  const out: TapeStep[] = [];
  let note: string | null = null;
  let tokens: number | null = null;
  for (const e of sorted) {
    const p = e.payload;
    if (e.event_type === "llm_call_end") {
      const n = typeof p.note === "string" && !p.note.startsWith("<") ? p.note : null;
      if (p.action === "finish") {
        out.push({ kind: "finish", key: e.event_id, reason: String(p.reason ?? "completed"), note: n, unreadable: p.unparsed === true, tMs: at(e) });
        note = null;
      } else {
        note = n;
        const a = e.attributes;
        const tin = Number(a["gen_ai.usage.input_tokens"] ?? NaN);
        const tout = Number(a["gen_ai.usage.output_tokens"] ?? NaN);
        tokens = Number.isFinite(tin) && Number.isFinite(tout) ? tin + tout : null;
      }
    } else if (e.event_type === "tool_call_end") {
      out.push({
        kind: "tool",
        key: e.event_id,
        callIndex: Number(e.attributes.call_index ?? out.length),
        tool: e.tool_name ?? "tool",
        args: obj(p.input_redacted),
        ok: e.status === "ok",
        result: p.output ? obj(p.output) : null,
        errorCode: typeof p.error_code === "string" ? p.error_code : null,
        error: typeof p.error_message === "string" ? p.error_message : null,
        note,
        tokens,
        tMs: at(e),
        intervention: typeof e.attributes.intervention === "string" ? e.attributes.intervention : null,
        spanId: e.span_id,
      });
      note = null;
      tokens = null;
    } else if (e.event_type === "budget_exhausted") {
      out.push({ kind: "budget", key: e.event_id, max: typeof p.max_tool_calls === "number" ? p.max_tool_calls : null, tMs: at(e) });
    }
  }
  return out;
}

type ToolStep = Extract<TapeStep, { kind: "tool" }>;

function sameFailure(a: ToolStep, b: ToolStep): boolean {
  return (
    !a.ok && !b.ok && !a.intervention && !b.intervention && a.tool === b.tool &&
    a.errorCode === b.errorCode && JSON.stringify(a.args) === JSON.stringify(b.args)
  );
}

/** first step key -> keys of the identical failing steps right after it (3+ in a row). */
export function findRepeats(steps: TapeStep[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  let i = 0;
  while (i < steps.length) {
    const head = steps[i];
    let j = i + 1;
    if (head.kind === "tool") {
      while (j < steps.length) {
        const next = steps[j];
        if (next.kind !== "tool" || !sameFailure(head, next)) break;
        j++;
      }
      if (j - i >= 3) out.set(head.key, steps.slice(i + 1, j).map((x) => x.key));
    }
    i = j;
  }
  return out;
}

