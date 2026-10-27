"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, tokenStore, wsUrl, type ProductRow } from "@/lib/api";
import { RealtimeClient, type ConnectionState, type RealtimeMessage, type Topic } from "@/lib/realtime";

export function useRealtime(topics: Topic[], onMessage: (m: RealtimeMessage) => void): ConnectionState {
  const [state, setState] = useState<ConnectionState>("closed");
  const handler = useRef(onMessage);
  handler.current = onMessage;
  const key = topics.join(",");
  useEffect(() => {
    if (!tokenStore.get()) return;
    const client = new RealtimeClient(() => wsUrl(key ? (key.split(",") as Topic[]) : []), (m) => handler.current(m), setState);
    client.start();
    return () => client.stop();
  }, [key]);
  return state;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn()
      .then((d) => live && (setData(d), setError(null)))
      .catch((e: Error) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}

/** product id -> name, loaded once; unknown ids are fetched on demand. */
export function useProductNames(): (id: string | null | undefined) => string {
  const [names, setNames] = useState<Record<string, string>>({});
  const asked = useRef<Set<string>>(new Set());
  useEffect(() => {
    api.products().then((rows: ProductRow[]) => setNames(Object.fromEntries(rows.map((p) => [p.id, p.name])))).catch(() => {});
  }, []);
  return useCallback(
    (id) => {
      if (!id) return "Unknown product";
      if (names[id]) return names[id];
      if (!asked.current.has(id)) {
        asked.current.add(id);
        api.product(id).then((p) => setNames((n) => ({ ...n, [id]: p.name }))).catch(() => {});
      }
      return "…";
    },
    [names],
  );
}

/** Re-renders every second so "N sec ago" labels stay live. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
