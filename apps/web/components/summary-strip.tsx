"use client";

import type { ReactNode } from "react";
import { StatusBadge } from "./ui";

export type StripData = {
  status: string;
  situation: string;
  agent: string;
  steps: number;
  stepLimit: number | null;
  duration: string;
  tokens: number | null;
  rootCause: string | null;
  passed: boolean;
  action: { label: string; onClick?: () => void; href?: string } | null;
};

function Cell({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 px-4 py-3 ${className}`}>
      <p className="text-[12.5px] text-fg-2">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

/** One line that answers "how did this run go" before anything else is read. */
export function SummaryStrip({ d }: { d: StripData }) {
  return (
    <div data-testid="summary-strip"
      className="grid grid-cols-2 overflow-hidden rounded-[12px] border border-line bg-surface sm:grid-cols-3 lg:grid-cols-[auto_minmax(0,1.1fr)_minmax(0,1fr)_auto_auto_auto_minmax(0,1.5fr)_minmax(0,1.35fr)] lg:divide-x lg:divide-line">
      <Cell label="Status"><StatusBadge status={d.status} size="lg" /></Cell>
      <Cell label="Situation"><p className="truncate font-medium" title={d.situation}>{d.situation}</p></Cell>
      <Cell label="Agent"><p className="truncate" title={d.agent}>{d.agent}</p></Cell>
      <Cell label="Steps">
        <p className="num text-[22px] font-semibold leading-6">
          {d.steps}
          {d.stepLimit ? <span className="text-[15px] font-normal text-fg-2"> of {d.stepLimit}</span> : null}
        </p>
      </Cell>
      <Cell label="Time"><p className="num text-[22px] font-semibold leading-6">{d.duration}</p></Cell>
      <Cell label="Tokens">
        <p className={`num text-[22px] font-semibold leading-6 ${d.tokens ? "text-ai" : "text-fg-3"}`}>{d.tokens ? d.tokens.toLocaleString() : "none"}</p>
      </Cell>
      <Cell label={d.passed ? "Problems" : "Root cause"} className="col-span-2 sm:col-span-1">
        <p className={`line-clamp-2 font-medium leading-5 ${d.passed ? "text-ok" : "text-bad"}`} data-testid="strip-root-cause">
          {d.rootCause ?? (d.passed ? "None found" : "Not identified")}
        </p>
      </Cell>
      <Cell label="Recommended action" className="col-span-2 bg-context-tint/50 sm:col-span-2 lg:col-span-1">
        {d.action ? (
          d.action.href ? (
            <a href={d.action.href} className="line-clamp-2 font-medium leading-5 text-context underline underline-offset-4">{d.action.label}</a>
          ) : (
            <button type="button" onClick={d.action.onClick} className="line-clamp-2 text-left font-medium leading-5 text-context underline underline-offset-4" data-testid="strip-action">
              {d.action.label}
            </button>
          )
        ) : (
          <p className="text-fg-2">None needed</p>
        )}
      </Cell>
    </div>
  );
}
