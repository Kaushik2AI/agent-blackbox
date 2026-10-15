"use client";

import { usePathname } from "next/navigation";
import { href } from "@/lib/format";

const LINKS = [
  { path: "/", label: "Overview" },
  { path: "/runs", label: "Runs" },
  { path: "/system", label: "System" },
];

export function Nav() {
  const pathname = usePathname() ?? "/";
  const active = (p: string) => (p === "/" ? pathname === "/" : pathname.startsWith(p));
  return (
    <header className="border-b border-line bg-panel/60">
      <nav aria-label="Main" className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
        <a href={href("/")} className="font-mono text-sm font-semibold tracking-tight">
          <span className="text-ok">■</span> agent blackbox
        </a>
        <ul className="flex gap-1 text-sm">
          {LINKS.map((l) => (
            <li key={l.path}>
              <a
                href={href(l.path)}
                aria-current={active(l.path) ? "page" : undefined}
                className={`rounded px-2.5 py-1.5 hover:bg-line focus-visible:outline-2 focus-visible:outline-ok ${
                  active(l.path) ? "bg-line text-[#e6edf3]" : "text-muted"
                }`}
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
