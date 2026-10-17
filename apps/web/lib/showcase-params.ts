/**
 * Build-time route lists for the static showcase (server only). In a normal build these are
 * empty and the run pages render on demand as usual.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

type Index = { executions: string[]; replays: string[] };

function index(): Index | null {
  if (process.env.NEXT_PUBLIC_SHOWCASE !== "1") return null;
  const file = join(process.cwd(), "public", "snapshot", "index.json");
  return JSON.parse(readFileSync(file, "utf8")) as Index;
}

export function runParams(): { id: string }[] {
  return (index()?.executions ?? []).map((id) => ({ id }));
}

export function replayParams(): { jobId: string }[] {
  return (index()?.replays ?? []).map((jobId) => ({ jobId }));
}
