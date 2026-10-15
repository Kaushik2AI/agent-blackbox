"use client";

import { useCallback, useEffect, useState } from "react";
import { checkConnectivity, type CheckResult, type ConnectivityState } from "@/lib/api";

const POLL_MS = 5000;

type Tone = "ok" | "warn" | "bad" | "idle";

const toneClass: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  idle: "bg-muted animate-pulse",
};

function Row({ name, tone, value, detail }: { name: string; tone: Tone; value: string; detail: string }) {
  return (
    <li className="flex items-start gap-4 px-5 py-4">
      <span aria-hidden className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${toneClass[tone]}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <span className="font-medium">{name}</span>
          <span className="font-mono text-sm text-muted">{value}</span>
        </div>
        <p className="mt-1 break-words font-mono text-xs text-muted">{detail}</p>
      </div>
    </li>
  );
}

function checkRow(name: string, check: CheckResult | undefined) {
  if (!check) return <Row key={name} name={name} tone="bad" value="missing" detail="not reported by /readyz" />;
  return (
    <Row
      key={name}
      name={name}
      tone={check.ok ? "ok" : "bad"}
      value={check.ok ? `${check.latency_ms.toFixed(1)} ms` : "down"}
      detail={check.detail}
    />
  );
}

export function StatusPanel() {
  const [state, setState] = useState<ConnectivityState | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    setState(await checkConnectivity());
    setBusy(false);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const summary =
    state === null
      ? { tone: "idle" as Tone, text: "Checking…" }
      : state.kind === "ready"
        ? { tone: "ok" as Tone, text: "All systems ready" }
        : state.kind === "degraded"
          ? { tone: "warn" as Tone, text: "API up, a dependency is not ready" }
          : { tone: "bad" as Tone, text: "API unreachable" };

  return (
    <section aria-labelledby="status-heading" className="rounded-lg border border-line bg-panel">
      <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
        <div className="flex items-center gap-3" aria-live="polite">
          <span aria-hidden className={`h-3 w-3 rounded-full ${toneClass[summary.tone]}`} />
          <h2 id="status-heading" className="font-semibold" data-testid="summary">
            {summary.text}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy}
          className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ok disabled:opacity-50"
        >
          {busy ? "Checking…" : "Re-check"}
        </button>
      </div>

      <ul className="divide-y divide-line">
        {state === null && <Row name="API" tone="idle" value="…" detail="waiting for first response" />}
        {state?.kind === "unreachable" && (
          <Row name="API" tone="bad" value="unreachable" detail={state.reason} />
        )}
        {state && state.kind !== "unreachable" && (
          <>
            <Row
              name="API"
              tone="ok"
              value={state.health.environment}
              detail={`${state.health.service} answered /healthz`}
            />
            {checkRow("PostgreSQL", state.readiness.checks.database)}
            {checkRow("Redis", state.readiness.checks.redis)}
          </>
        )}
      </ul>

      {state && (
        <p className="border-t border-line px-5 py-3 font-mono text-xs text-muted">
          last checked {state.checkedAt.toLocaleTimeString()} · auto-refresh every {POLL_MS / 1000}s
        </p>
      )}
    </section>
  );
}
