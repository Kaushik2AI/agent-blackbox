"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type ApiState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/** Runs `load` when `key` changes; ignores responses that arrive after a newer request. */
export function useApi<T>(load: () => Promise<T>, key: string): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const latest = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    loadRef.current().then(
      (value) => {
        if (id !== latest.current) return;
        setData(value);
        setLoading(false);
      },
      (err: unknown) => {
        if (id !== latest.current) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      },
    );
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
