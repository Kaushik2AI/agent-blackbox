"use client";

import type { ReactNode } from "react";

const STATUS_TONE: Record<string, string> = {
  succeeded: "bg-ok/15 text-ok ring-ok/30",
  ok: "bg-ok/15 text-ok ring-ok/30",
  failed: "bg-bad/15 text-bad ring-bad/30",
  error: "bg-bad/15 text-bad ring-bad/30",
  running: "bg-warn/15 text-warn ring-warn/30",
  pending: "bg-muted/15 text-muted ring-muted/30",
  aborted: "bg-muted/15 text-muted ring-muted/30",
  unset: "bg-muted/15 text-muted ring-muted/30",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] font-medium ring-1 ring-inset ${STATUS_TONE[status] ?? STATUS_TONE.unset}`}
    >
      {status}
    </span>
  );
}

export function Tag({ children, tone = "bad" }: { children: ReactNode; tone?: "bad" | "muted" }) {
  const cls = tone === "bad" ? "border-bad/40 text-bad" : "border-line text-muted";
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[11px] ${cls}`}>
      {children}
    </span>
  );
}

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-panel ${className}`}>
      {title && (
        <h2 className="border-b border-line px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 px-4 py-10 text-sm text-muted">
      <span className="h-2 w-2 animate-pulse rounded-full bg-muted" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-4 rounded-md border border-bad/40 bg-bad/10 px-4 py-3 text-sm">
      <p className="font-medium text-bad">Request failed</p>
      <p className="mt-1 break-words font-mono text-xs text-muted">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}
          className="mt-3 rounded border border-line px-3 py-1 text-xs hover:bg-line focus-visible:outline-2 focus-visible:outline-ok">
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyRuns() {
  return (
    <div className="px-4 py-10 text-sm text-muted">
      <p className="font-medium text-[#e6edf3]">No runs recorded yet.</p>
      <p className="mt-2">
        Record real demo-agent runs through the ingest API, then refresh:
      </p>
      <pre className="mt-3 overflow-x-auto rounded bg-ink px-3 py-2 font-mono text-xs text-[#e6edf3]">make seed-demo</pre>
    </div>
  );
}

export function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}
