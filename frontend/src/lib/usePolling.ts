"use client";

/**
 * Nexus - Polling hook with abort + visibility-aware pausing
 * - Cancels in-flight fetches on unmount / symbol change (no wasted work)
 * - Pauses interval when the document is hidden (saves bandwidth + CPU)
 * - Refetches immediately when the tab regains focus
 * - Swallows AbortError silently; surfaces real errors
 */

import { useEffect, useRef, useState, useCallback } from "react";

interface UsePollingOptions<T> {
  url: string | null;
  intervalMs: number;
  /** Parse/transform response. Defaults to r.json() */
  parse?: (res: Response) => Promise<T>;
  /** Disable the hook */
  enabled?: boolean;
}

export function usePolling<T>({
  url,
  intervalMs,
  parse,
  enabled = true,
}: UsePollingOptions<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (!url || !enabled) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const res = await fetch(url, { signal: ac.signal });
      if (!res.ok) throw new Error(`HTTP ${String(res.status)}`);
      const json: T = parse ? await parse(res) : ((await res.json()) as T);
      if (!ac.signal.aborted) {
        setData(json);
        setError(null);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      if (e instanceof Error && e.name === "AbortError") return;
      if (!ac.signal.aborted) {
        setError(e instanceof Error ? e.message : "Request failed");
      }
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [url, enabled, parse]);

  // Start / restart polling
  useEffect(() => {
    if (!enabled || !url) return undefined;
    setLoading(true);
    void fetchOnce();

    const start = () => {
      if (timerRef.current) return;
      timerRef.current = setInterval(() => { void fetchOnce(); }, intervalMs);
    };
    const stop = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };

    if (!document.hidden) start();

    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        void fetchOnce();
        start();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
      abortRef.current?.abort();
    };
  }, [fetchOnce, intervalMs, enabled, url]);

  return { data, loading, error, refetch: fetchOnce };
}
