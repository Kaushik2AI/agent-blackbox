"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { checkConnectivity } from "@/lib/api";
import { SHOWCASE } from "@/lib/showcase";
import { href } from "@/lib/format";
import { useViewMode } from "@/lib/view-mode";
import { Segmented } from "./ui";

const LINKS = [
  { path: "/", label: "Live demo" },
  { path: "/runs", label: "Runs" },
  { path: "/benchmark", label: "Benchmark" },
];

/** The FlightPath mark: a route with two waypoints and a landing square. */
export function Mark({ className = "h-5 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 28 20" className={className} aria-hidden>
      <path d="M2 14 C 8 14, 9 6, 14 6 S 20 12, 24 8" fill="none" stroke="#151a24" strokeWidth="2" strokeLinecap="round" />
      <circle cx="2.5" cy="14" r="2.3" fill="#2160c4" />
      <circle cx="14" cy="6" r="2.3" fill="#6a3bd2" />
      <rect x="21.5" y="5.5" width="5" height="5" rx="1" fill="#11774a" />
    </svg>
  );
}

export function Nav() {
  const pathname = usePathname() ?? "/";
  const [mode, setMode] = useViewMode();
  const active = (p: string) =>
    p === "/" ? pathname === "/" : pathname.startsWith(p) || (p === "/runs" && pathname.startsWith("/replays"));
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <nav aria-label="Main" className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:gap-6 sm:px-6">
        <a href={href("/")} className="flex items-center gap-2 text-[17px] font-semibold tracking-tight" aria-label="FlightPath home">
          <Mark />
          FlightPath
        </a>
        <ul className="flex gap-1">
          {LINKS.map((l) => (
            <li key={l.path}>
              <a href={href(l.path)} aria-current={active(l.path) ? "page" : undefined}
                className={`whitespace-nowrap rounded-[8px] px-2.5 py-1.5 text-[15px] sm:px-3 ${active(l.path) ? "bg-well font-medium text-fg" : "text-fg-2 hover:text-fg"}`}>
                {l.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="ml-auto flex items-center gap-4">
          <div className="hidden sm:block">
            <Segmented label="Detail level" testId="view-mode" value={mode} onChange={setMode}
              options={[{ id: "simple", label: "Simple view" }, { id: "technical", label: "Technical view" }]} />
          </div>
          <StatusDot />
        </div>
      </nav>
    </header>
  );
}

function StatusDot() {
  const [state, setState] = useState<"checking" | "ready" | "degraded" | "down">("checking");
  useEffect(() => {
    let alive = true;
    const run = () =>
      checkConnectivity().then((c) => {
        if (alive) setState(c.kind === "ready" ? "ready" : c.kind === "degraded" ? "degraded" : "down");
      });
    run();
    const t = setInterval(run, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const label = { checking: "Checking", ready: SHOWCASE ? "Snapshot" : "Online", degraded: "Degraded", down: "Offline" }[state];
  const color = { checking: "bg-fg-3", ready: "bg-ok", degraded: "bg-warn", down: "bg-bad" }[state];
  return (
    <a href={href("/system")} className="flex items-center gap-2 text-[13.5px] text-fg-2 hover:text-fg" title="System status">
      <span aria-hidden className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </a>
  );
}
