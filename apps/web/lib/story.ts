/**
 * Turns a recording into a story: beats on the flight path (with identical failing
 * attempts folded into one loop), the most likely root cause kept apart from its
 * symptoms, and a plain-English summary. Pure functions, unit-tested.
 */
import type { Finding } from "./api";
import { errorText, toolTitle } from "./describe";
import { findRepeats, type TapeStep } from "./steps";

export type ToolStep = Extract<TapeStep, { kind: "tool" }>;
export type EndStep = Extract<TapeStep, { kind: "finish" | "budget" }>;

export type Beat =
  | { kind: "step"; key: string; step: ToolStep }
  | { kind: "loop"; key: string; head: ToolStep; repeats: ToolStep[] }
  | { kind: "end"; key: string; step: EndStep };

/** Beats in order. A loop is the identical failing attempts AFTER the first one, which
 * stays a normal waypoint (it is usually the root cause). `unfold` lists loops to show
 * expanded. */
export function buildBeats(steps: TapeStep[], opts: { fold: boolean; unfold?: Set<string> } = { fold: true }): Beat[] {
  const repeats = opts.fold ? findRepeats(steps) : new Map<string, string[]>();
  const hidden = new Map<string, string>(); // repeat key -> head key
  repeats.forEach((rest, head) => {
    if (!opts.unfold?.has(head)) rest.forEach((k) => hidden.set(k, head));
  });
  const byKey = new Map(steps.map((s) => [s.key, s]));
  const out: Beat[] = [];
  for (const s of steps) {
    if (hidden.has(s.key)) continue;
    if (s.kind === "tool") {
      out.push({ kind: "step", key: s.key, step: s });
      const rest = repeats.get(s.key);
      if (rest && !opts.unfold?.has(s.key)) {
        out.push({ kind: "loop", key: `loop-${s.key}`, head: s, repeats: rest.map((k) => byKey.get(k) as ToolStep) });
      }
    } else {
      out.push({ kind: "end", key: s.key, step: s });
    }
  }
  return out;
}

// ------------------------------------------------------------------ wording helpers
const NOUN: Record<string, string> = {
  lookup_order: "order lookup",
  lookup_inventory: "stock check",
  get_policy: "policy lookup",
  draft_response: "reply writer",
  submit_resolution: "ticket system",
};

export function toolNoun(tool: string | null | undefined): string {
  return (tool && NOUN[tool]) || "tool";
}

function str(v: unknown): string | null {
  return typeof v === "string" && !(v.startsWith("<") && v.endsWith(">")) ? v : null;
}

/** "looked up order ORD-1001", for sentences. */
export function pastTense(s: ToolStep): string {
  const a = s.args;
  switch (s.tool) {
    case "lookup_order":
      return str(a.order_id) ? `looked up order ${str(a.order_id)}` : "looked up the order";
    case "lookup_inventory":
      if (str(a.sku)) return `checked stock for ${str(a.sku)}`;
      if (str(a.product_name)) return `asked the stock system about “${str(a.product_name)}” by name`;
      return "checked stock";
    case "get_policy":
      return str(a.policy_key) ? `read the ${str(a.policy_key)} policy` : "read the policy";
    case "draft_response":
      return "wrote a reply to the customer";
    case "submit_resolution": {
      const c = str(a.choice);
      const o = str(a.order_id);
      return c ? `closed the ticket with a${/^[aeiou]/.test(c) ? "n" : ""} ${c}${o ? ` for ${o}` : ""}` : "closed the ticket";
    }
    default:
      return `used ${s.tool}`;
  }
}

function plainError(code: string | null): string {
  const t = errorText(code).replace(/^(Rejected|No answer): /, "");
  return t[0].toUpperCase() + t.slice(1);
}

function lowerFirst(s: string): string {
  return s ? s[0].toLowerCase() + s.slice(1) : s;
}

function joinList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

// ------------------------------------------------------------------ root cause
const PRIORITY = [
  "state_identity_mismatch",
  "stale_data",
  "tool_schema_mismatch",
  "tool_timeout",
  "repeated_action",
  "retry_loop",
  "budget_exhausted",
];

const SYMPTOM: Record<string, string> = {
  tool_schema_mismatch: "a tool rejected its input",
  retry_loop: "stuck in a loop",
  tool_timeout: "a system timed out",
  budget_exhausted: "ran out of steps",
  state_identity_mismatch: "order mix-up",
  repeated_action: "did a finished step again",
  stale_data: "acted on out-of-date data",
};

export function symptomLabel(category: string): string {
  return SYMPTOM[category] ?? category.replaceAll("_", " ");
}

export type RootCause = {
  title: string;
  detail: string;
  category: string | null;
  finding: Finding | null;
  symptoms: Finding[];
  /** The step that shows the cause (first evidence step), if any. */
  step: ToolStep | null;
};

function evidenceStep(f: Finding, steps: ToolStep[]): ToolStep | null {
  // For a repeat, the interesting step is the second copy, not the first.
  if (f.category === "repeated_action") return repeatedStep(steps);
  const bySpan = steps.find((s) => s.spanId && f.evidence_span_ids.includes(s.spanId));
  if (bySpan) return bySpan;
  // Live recordings carry no span ids: fall back to the first step that matches.
  if (f.category === "tool_schema_mismatch") return steps.find((s) => !s.ok && s.errorCode !== "TIMEOUT") ?? null;
  if (f.category === "tool_timeout") return steps.find((s) => s.errorCode === "TIMEOUT") ?? null;
  if (f.category === "retry_loop") return steps.find((s) => !s.ok) ?? null;
  if (f.category === "state_identity_mismatch") return steps.find((s) => s.tool === "submit_resolution") ?? null;
  if (f.category === "stale_data") return steps.find((s) => s.tool === "lookup_inventory" && s.ok) ?? null;
  return null;
}

/** The first successful draft/resolution step that repeats an earlier one. */
function repeatedStep(steps: ToolStep[]): ToolStep | null {
  const seen = new Set<string>();
  for (const s of steps) {
    if (!s.ok || (s.tool !== "draft_response" && s.tool !== "submit_resolution")) continue;
    if (seen.has(s.tool)) return s;
    seen.add(s.tool);
  }
  return null;
}

export function rootCause(
  findings: Finding[],
  steps: TapeStep[],
  outcome: { passed: boolean | null; reasons?: string[]; termination?: string | null },
): RootCause | null {
  const tools = steps.filter((s): s is ToolStep => s.kind === "tool");
  const rank = (f: Finding) => {
    const i = PRIORITY.indexOf(f.category);
    return i === -1 ? PRIORITY.length : i;
  };
  const ranked = [...findings].sort((a, b) => rank(a) - rank(b));
  const main = ranked[0] ?? null;
  if (!main) {
    if (outcome.passed) return null;
    const reasons = outcome.reasons ?? [];
    const wrong = reasons.some((r) => r.startsWith("wrong_resolution"));
    return {
      title: wrong ? "Finished with the wrong decision" : "Stopped before closing the ticket",
      detail: "None of the automatic checks matched. Read the path to see where it went off course.",
      category: null,
      finding: null,
      symptoms: [],
      step: null,
    };
  }
  const step = evidenceStep(main, tools);
  const noun = toolNoun(step?.tool);
  let title: string;
  let detail: string;
  switch (main.category) {
    case "tool_schema_mismatch":
      title = `Wrong input to the ${noun}`;
      detail = step ? plainError(step.errorCode) : "A tool rejected what the agent sent.";
      break;
    case "tool_timeout":
      title = `The ${noun} stopped answering`;
      detail = "The system the agent needed timed out, so the agent couldn't get what it needed.";
      break;
    case "state_identity_mismatch":
      title = "Closed the ticket on the wrong order";
      detail = "The agent looked up one order but recorded the decision against a different one.";
      break;
    case "stale_data":
      title = "Acted on out-of-date data";
      detail = "A tool answered from an old snapshot, and the agent made its decision on it. The live value may be different.";
      break;
    case "repeated_action":
      title = "Didn't stop when the work was done";
      detail =
        step?.tool === "draft_response"
          ? "The reply was already written, but the agent wrote it again. A one-step change can't fix this; the agent's instructions should say when the work is done."
          : "The ticket was already closed, but the agent closed it again. A one-step change can't fix this; the agent's instructions should say when the work is done.";
      break;
    case "retry_loop":
      title = "Repeated a failing step";
      detail = "It tried the same thing again and again instead of changing its approach.";
      break;
    case "budget_exhausted":
      title = "Ran out of steps";
      detail = "Every agent gets a fixed number of steps. This one used them all before finishing.";
      break;
    default:
      title = main.title;
      detail = main.explanation;
  }
  return { title, detail, category: main.category, finding: main, symptoms: ranked.slice(1), step };
}

// ------------------------------------------------------------------ summary in plain words
export function narrate(
  steps: TapeStep[],
  outcome: { passed: boolean | null; termination?: string | null; fallback: string },
  cause: RootCause | null,
): string {
  const tools = steps.filter((s): s is ToolStep => s.kind === "tool");
  if (!tools.length) return outcome.fallback;
  const firstBad = tools.findIndex((s) => !s.ok);
  const budget = steps.find((s) => s.kind === "budget") as Extract<TapeStep, { kind: "budget" }> | undefined;
  const finish = steps.find((s) => s.kind === "finish") as Extract<TapeStep, { kind: "finish" }> | undefined;

  if (outcome.passed) {
    const did = joinList(tools.filter((s) => s.ok).slice(-3).map(pastTense));
    const hiccup = tools.some((s) => s.errorCode === "TIMEOUT")
      ? " A system timed out once on the way, but trying again worked."
      : "";
    return `The agent ${did}.${hiccup} The outcome check confirms this was the right answer.`;
  }

  if (cause?.category === "state_identity_mismatch") {
    const looked = tools.find((s) => s.tool === "lookup_order");
    const closed = tools.find((s) => s.tool === "submit_resolution");
    const a = looked ? str(looked.args.order_id) : null;
    const b = closed ? str(closed.args.order_id) : null;
    if (a && b && a !== b) {
      return `The agent looked up order ${a} but closed the ticket for order ${b}. The customer who wrote in got nothing, and someone else's order was changed.`;
    }
  }

  if (cause?.category === "repeated_action") {
    const count = (tool: string) => tools.filter((s) => s.ok && s.tool === tool).length;
    const times = (n: number) => (n === 2 ? "twice" : `${n} times`);
    const extra: string[] = [];
    if (count("draft_response") > 1) extra.push(`wrote the reply ${times(count("draft_response"))}`);
    if (count("submit_resolution") > 1) extra.push(`closed the ticket ${times(count("submit_resolution"))}`);
    return `The agent did the right steps, but it didn't stop when the work was done: it ${joinList(extra)}. Each extra call saved another copy, so the outcome check failed.`;
  }

  const parts: string[] = [];
  const before = firstBad > 0 ? tools.slice(0, firstBad).map(pastTense) : [];
  if (firstBad === -1) {
    parts.push(`The agent ${joinList(tools.slice(-3).map(pastTense))}.`);
  } else {
    const bad = tools[firstBad];
    const opener = before.length ? `The agent ${joinList(before.slice(-2))}. Then it ` : "The agent first ";
    parts.push(`${opener}${pastTense(bad)}, and ${lowerFirst(plainError(bad.errorCode)).replace(/\.$/, "")}.`);
    let same = 0;
    for (let i = firstBad + 1; i < tools.length; i++) {
      if (JSON.stringify(tools[i].args) === JSON.stringify(bad.args) && tools[i].tool === bad.tool && !tools[i].ok) same++;
      else break;
    }
    if (same >= 2) parts.push(`It tried exactly the same thing ${same} more times without changing anything.`);
  }
  if (budget) {
    const all = budget.max ? `all ${budget.max} of its steps` : "all of its steps";
    parts.push(`It used ${all}, so the customer never got an answer.`);
  } else if (finish && finish.reason !== "completed") {
    parts.push("Then it gave up, so the ticket stayed open.");
  } else if (outcome.termination === "completed" || finish) {
    parts.push(`It finished, but ${lowerFirst(outcome.fallback)}`);
  }
  return parts.join(" ");
}

/** Waypoint number shown to people (1-based) for a span id cited by a finding. */
export function stepNumberBySpan(steps: TapeStep[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const s of steps) if (s.kind === "tool" && s.spanId) out.set(s.spanId, s.callIndex + 1);
  return out;
}

export function stepTitle(s: ToolStep): string {
  return toolTitle(s.tool, s.args);
}
