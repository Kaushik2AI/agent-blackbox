"use client";

import type { ReactNode } from "react";
import { href } from "@/lib/format";

// ------------------------------------------------------------------ buttons
export const BTN_PRIMARY =
  "inline-flex items-center justify-center gap-2 rounded-[8px] bg-fg px-4 py-2 text-[15px] font-medium text-white hover:bg-[#2a3142] disabled:cursor-not-allowed disabled:opacity-40";
export const BTN_SECONDARY =
  "inline-flex items-center justify-center gap-2 rounded-[8px] border border-line-strong bg-surface px-3.5 py-1.5 text-[15px] text-fg hover:border-fg-3 disabled:cursor-not-allowed disabled:opacity-40";
export const BTN_QUIET =
  "inline-flex items-center gap-1.5 rounded-[6px] px-1.5 py-0.5 text-[13.5px] text-fg-2 underline decoration-line-strong underline-offset-4 hover:text-fg hover:decoration-fg-3";

// ------------------------------------------------------------------ tones
export type Tone = "context" | "ai" | "ok" | "warn" | "bad" | "neutral";

const PILL: Record<Tone, string> = {
  context: "bg-context-tint text-context",
  ai: "bg-ai-tint text-ai",
  ok: "bg-ok-tint text-ok",
  warn: "bg-warn-tint text-warn",
  bad: "bg-bad-tint text-bad",
  neutral: "bg-well text-fg-2",
};

export function Pill({ tone = "neutral", children, mono, title }: { tone?: Tone; children: ReactNode; mono?: boolean; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12.5px] font-medium leading-5 ${PILL[tone]} ${mono ? "font-mono text-[11.5px] font-normal" : ""}`}>
      {children}
    </span>
  );
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  succeeded: { label: "Passed", tone: "ok" },
  ok: { label: "OK", tone: "ok" },
  passed: { label: "Passed", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  error: { label: "Error", tone: "bad" },
  running: { label: "Running", tone: "context" },
  queued: { label: "Queued", tone: "neutral" },
  pending: { label: "Pending", tone: "neutral" },
  aborted: { label: "Aborted", tone: "neutral" },
  unset: { label: "Unknown", tone: "neutral" },
};

const DOT: Record<Tone, string> = {
  context: "bg-context", ai: "bg-ai", ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", neutral: "bg-fg-3",
};

/** Run / step status as dot + word. `data-status` keeps the raw value for tests. */
export function StatusBadge({ status, size = "md" }: { status: string; size?: "md" | "lg" }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <span data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${PILL[s.tone]} ${size === "lg" ? "px-3 py-1 text-[15px]" : "px-2 py-0.5 text-[12.5px]"}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${DOT[s.tone]} ${status === "running" ? "rec-dot" : ""}`} />
      {s.label}
    </span>
  );
}
export const StatusPill = StatusBadge;

/** Error codes and other raw identifiers: neutral, monospace. */
export function Tag({ children, tone = "bad" }: { children: ReactNode; tone?: "bad" | "muted" }) {
  const cls = tone === "bad" ? "bg-bad-tint text-bad" : "bg-well text-fg-2";
  return <span className={`inline-flex rounded-[5px] px-1.5 py-px font-mono text-[11.5px] ${cls}`}>{children}</span>;
}

// ------------------------------------------------------------------ surfaces
export function Card({ title, aside, children, className = "", tone }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; tone?: Tone;
}) {
  const edge = tone && tone !== "neutral" ? `border-t-[3px] ${({ context: "border-t-context", ai: "border-t-ai", ok: "border-t-ok", warn: "border-t-warn", bad: "border-t-bad" } as Record<string, string>)[tone]}` : "";
  return (
    <section className={`rounded-[12px] border border-line bg-surface ${edge} ${className}`}>
      {title && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 px-4 py-10 text-fg-2">
      <span className="rec-dot h-2 w-2 rounded-full bg-context" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-4 rounded-[8px] bg-bad-tint px-4 py-3">
      <p className="font-medium text-bad">Couldn&apos;t load this</p>
      <p className="mt-1 break-words font-mono text-xs text-fg-2">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className={`${BTN_SECONDARY} mt-3`}>Try again</button>
      )}
    </div>
  );
}

export function EmptyRuns() {
  return (
    <div className="px-5 py-12">
      <p className="text-[17px] font-semibold">No runs yet</p>
      <p className="mt-1 text-fg-2">Start one from the live demo and it appears here.</p>
      <a href={href("/")} className={`${BTN_PRIMARY} mt-4`}>Open the live demo</a>
    </div>
  );
}

export function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <p className="text-[13px] text-fg-2">{label}</p>
      <p className="num mt-0.5 truncate text-[26px] font-semibold leading-8">{value}</p>
      {hint && <p className="mt-0.5 truncate text-[12.5px] text-fg-3">{hint}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ controls
export function Tabs<T extends string>({ tabs, value, onChange, label }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void; label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button key={t.id} type="button" role="tab" aria-selected={active} data-testid={`tab-${t.id}`}
            onClick={() => onChange(t.id)}
            className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-[15px] ${active ? "border-fg font-semibold text-fg" : "border-transparent text-fg-2 hover:text-fg"}`}>
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className={`num rounded-full px-1.5 text-[12.5px] ${active ? "bg-fg text-white" : "bg-well text-fg-2"}`}>{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label, testId }: {
  options: { id: T; label: string }[]; value: T; onChange: (v: T) => void; label: string; testId?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} data-testid={testId} className="inline-flex rounded-[8px] bg-well p-0.5">
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={o.id === value} onClick={() => onChange(o.id)}
          className={`rounded-[6px] px-2.5 py-1 text-[13.5px] ${o.id === value ? "bg-surface font-medium text-fg shadow-[0_1px_2px_rgba(21,26,36,.12)]" : "text-fg-2 hover:text-fg"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Progressive disclosure: secondary detail one click away. */
export function Disclosure({ label, children, testId, defaultOpen = false }: {
  label: ReactNode; children: ReactNode; testId?: string; defaultOpen?: boolean;
}) {
  return (
    <details className="group" data-testid={testId} open={defaultOpen}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[13.5px] text-fg-2 hover:text-fg [&::-webkit-details-marker]:hidden">
        <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3 transition-transform group-open:rotate-90"><path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
        {label}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function JsonBlock({ value, max = "max-h-64" }: { value: unknown; max?: string }) {
  return (
    <pre className={`${max} overflow-auto rounded-[8px] bg-well px-3 py-2 font-mono text-[12px] leading-[18px] text-fg`}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// ------------------------------------------------------------------ icons (16px, currentColor)
export function Icon({ name, className = "h-4 w-4" }: { name: "check" | "x" | "alert" | "loop" | "flag" | "spark" | "arrow" | "clock"; className?: string }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg aria-hidden viewBox="0 0 16 16" className={className}>
      {name === "check" && <path d="M3.5 8.5l3 3 6-7" {...p} />}
      {name === "x" && <path d="M4.5 4.5l7 7m0-7l-7 7" {...p} />}
      {name === "alert" && <><path d="M8 2.5l6 11H2z" {...p} /><path d="M8 7v3" {...p} /><circle cx="8" cy="12" r=".6" fill="currentColor" /></>}
      {name === "loop" && <><path d="M12.5 6.5A4.8 4.8 0 1 0 13 9" {...p} /><path d="M13 3v3.6H9.4" {...p} /></>}
      {name === "flag" && <><path d="M4 14V2.5" {...p} /><path d="M4 3h7.5l-1.8 2.6L11.5 8H4" {...p} /></>}
      {name === "spark" && <path d="M8 2v3m0 6v3M2 8h3m6 0h3M4 4l1.8 1.8m4.4 4.4L12 12M12 4l-1.8 1.8M5.8 10.2L4 12" {...p} />}
      {name === "arrow" && <path d="M3 8h10m-4-4l4 4-4 4" {...p} />}
      {name === "clock" && <><circle cx="8" cy="8" r="5.5" {...p} /><path d="M8 5v3l2 1.5" {...p} /></>}
    </svg>
  );
}
