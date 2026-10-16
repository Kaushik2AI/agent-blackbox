/**
 * Plain-language wording for steps, findings and outcomes. Everything a visitor reads
 * about a run goes through here, so the vocabulary stays consistent across pages.
 */
import type { Finding } from "./api";
import type { TapeStep } from "./steps";

export type Tone = "ok" | "bad" | "warn" | "muted";

/** A recorded value, or null when the run stored only its shape (metadata-only capture). */
function val(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v.startsWith("<") && v.endsWith(">") ? null : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const ERRORS: Record<string, string> = {
  SKU_REQUIRED: "Rejected: the stock system needs a product code (SKU), not a product name.",
  INVALID_ARGUMENT: "Rejected: the input didn't match what this tool accepts.",
  TIMEOUT: "No answer: the system timed out.",
  ORDER_NOT_FOUND: "No order with that number.",
  SKU_NOT_FOUND: "No stock record for that product code.",
  POLICY_NOT_FOUND: "No policy with that name.",
  UNKNOWN_TOOL: "That tool doesn't exist.",
};

export function errorText(code: string | null): string {
  return (code && ERRORS[code]) || "The tool returned an error.";
}

export function toolTitle(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case "lookup_order":
      return val(args.order_id) ? `Look up order ${val(args.order_id)}` : "Look up the order";
    case "lookup_inventory": {
      const sku = val(args.sku);
      const name = val(args.product_name);
      if (sku) return `Check stock for ${sku}`;
      if (name) return `Check stock for “${name}”`;
      return "Check stock";
    }
    case "get_policy":
      return val(args.policy_key) ? `Read the ${val(args.policy_key)} policy` : "Read a policy";
    case "draft_response":
      return "Write a reply to the customer";
    case "submit_resolution": {
      const choice = val(args.choice);
      const order = val(args.order_id);
      return choice && order ? `Close the ticket: ${choice} for ${order}` : "Close the ticket";
    }
    default:
      return `Use “${tool}”`;
  }
}

function resultText(tool: string, args: Record<string, unknown>, r: Record<string, unknown> | null): string | null {
  if (!r) return null;
  switch (tool) {
    case "lookup_order": {
      const name = val(r.product_name);
      const sku = val(r.sku);
      const ship = val(r.shipping_status);
      return name ? `${name}${sku ? ` (${sku})` : ""}${ship ? `, ${ship}` : ""}` : null;
    }
    case "lookup_inventory":
      if (r.available === true) return val(r.quantity) ? `In stock: ${val(r.quantity)}` : "In stock";
      if (r.available === false) return "Out of stock";
      return null;
    case "get_policy":
      return val(r.text) ? clip(val(r.text) as string, 140) : null;
    case "draft_response":
      return val(args.text) ? `“${clip(val(args.text) as string, 180)}”` : "Draft saved";
    case "submit_resolution":
      return "Saved";
    default:
      return null;
  }
}

export type StepView = { title: string; detail: string | null; tone: Tone };

export function describeStep(s: TapeStep): StepView {
  if (s.kind === "budget") {
    return {
      title: s.max ? `Stopped: all ${s.max} allowed steps used` : "Stopped: out of steps",
      detail: "The agent hadn't finished, so the run was cut off.",
      tone: "bad",
    };
  }
  if (s.kind === "finish") {
    if (s.unreadable) return { title: "Stopped: the AI's reply couldn't be understood", detail: s.note, tone: "bad" };
    return s.reason === "completed"
      ? { title: "Agent says it's done", detail: s.note, tone: "muted" }
      : { title: "Agent gave up", detail: s.note, tone: "bad" };
  }
  const title = toolTitle(s.tool, s.args);
  if (s.ok) return { title, detail: resultText(s.tool, s.args, s.result), tone: "ok" };
  return { title, detail: errorText(s.errorCode), tone: s.errorCode === "TIMEOUT" ? "warn" : "bad" };
}

// ------------------------------------------------------------------ findings
const FINDING_TITLES: Record<string, string> = {
  tool_schema_mismatch: "A tool rejected the agent's input",
  retry_loop: "The agent kept repeating the same failing step",
  tool_timeout: "A system the agent needed never answered",
  budget_exhausted: "The agent ran out of steps",
  state_identity_mismatch: "The agent mixed up which order it was handling",
};

const FINDING_PLAIN: Record<string, string> = {
  tool_schema_mismatch: "The agent sent the wrong kind of information, so the tool said no.",
  retry_loop: "Instead of changing its approach, it tried the exact same thing again and again.",
  tool_timeout: "A system the agent depends on didn't reply in time.",
  budget_exhausted: "Every agent gets a fixed number of steps. This one used them all before finishing.",
  state_identity_mismatch: "It looked up one order but closed the ticket for a different one.",
};

/** One short sentence anyone can follow; the detector's own wording goes under "details". */
export function findingPlain(f: Pick<Finding, "category" | "explanation">): string {
  return FINDING_PLAIN[f.category] ?? f.explanation;
}

export function findingTitle(f: Pick<Finding, "category" | "title">): string {
  return FINDING_TITLES[f.category] ?? f.title;
}

// ------------------------------------------------------------------ outcome
export type Verdict = { passed: boolean; headline: string; line: string };

export function verdict(input: {
  passed: boolean | null | undefined;
  termination?: string | null;
  reasons?: string[];
  categories?: string[];
}): Verdict {
  const cats = new Set(input.categories ?? []);
  const reasons = input.reasons ?? [];
  if (input.passed) {
    return {
      passed: true,
      headline: "Solved",
      line: cats.size
        ? "The ticket was closed correctly, though something went wrong on the way."
        : "The agent closed the ticket correctly.",
    };
  }
  let line = "The ticket wasn't closed correctly.";
  if (cats.has("state_identity_mismatch")) {
    line = "The agent closed the ticket on a different order than the one it looked up.";
  } else if (cats.has("retry_loop") && cats.has("tool_schema_mismatch")) {
    line = "The agent kept repeating a step the tool had rejected, until it ran out of steps.";
  } else if (cats.has("tool_timeout")) {
    line = "A system the agent needed never answered, so it couldn't finish.";
  } else if (cats.has("budget_exhausted") || input.termination === "budget_exhausted") {
    line = "The agent ran out of steps before finishing.";
  } else if (reasons.some((r) => r.startsWith("wrong_resolution"))) {
    line = "The agent finished, but with the wrong decision.";
  } else if (reasons.includes("no_resolution_submitted")) {
    line = "The agent stopped without closing the ticket.";
  }
  return { passed: false, headline: "Failed", line };
}

export function agentLabel(modelName: string | null | undefined, llmLabel?: string): string {
  if (!modelName) return "Agent";
  if (modelName.startsWith("llm:")) return llmLabel ? `Live AI (${llmLabel})` : `Live AI (${modelName.slice(4)})`;
  return "Scripted agent";
}

export function fmtClock(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  const s = ms / 1000;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const diff = Math.max(0, now - Date.parse(iso)) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
