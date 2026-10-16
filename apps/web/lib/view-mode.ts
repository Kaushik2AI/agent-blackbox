"use client";

/**
 * Simple view / Technical view: one switch for the whole app, remembered per browser.
 * It changes how much detail is shown (tool names, codes, tokens, raw data), never the
 * structure of a page.
 */
import { useSyncExternalStore } from "react";

export type ViewMode = "simple" | "technical";

const KEY = "flightpath.view";
const listeners = new Set<() => void>();
let memory: ViewMode = "simple";

function read(): ViewMode {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "simple" || v === "technical") memory = v;
  } catch {
    /* storage blocked: keep the in-memory value */
  }
  return memory;
}

export function setViewMode(mode: ViewMode): void {
  memory = mode;
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useViewMode(): [ViewMode, (m: ViewMode) => void] {
  const mode = useSyncExternalStore(subscribe, read, () => "simple" as ViewMode);
  return [mode, setViewMode];
}
