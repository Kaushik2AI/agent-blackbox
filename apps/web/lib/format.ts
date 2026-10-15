/** Small formatting and URL helpers shared by the dashboard. */

/**
 * In-app link. When the app is served behind a path-stripping proxy (SCC OnDemand VS Code),
 * NEXT_PUBLIC_BASE_PATH holds the browser-visible prefix; plain <a href> links built with
 * this helper keep working there, where client-side router links would not.
 */
export function href(path: string): string {
  return `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}${path}`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms.toFixed(1)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function shortId(id: string, n = 8): string {
  return id.length > n ? id.slice(0, n) : id;
}

export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)}%`;
}

export const SINCE_OPTIONS = [
  { value: "", label: "All time" },
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
] as const;

export function sinceToIso(since: string, now: Date = new Date()): string | undefined {
  const hours = { "1h": 1, "24h": 24, "7d": 168 }[since];
  return hours ? new Date(now.getTime() - hours * 3600_000).toISOString() : undefined;
}
