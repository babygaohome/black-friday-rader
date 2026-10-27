"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ALERT_LABEL, ago, money } from "@/lib/format";
import { useLoad, useNow, useProductNames, useRealtime } from "@/lib/hooks";
import type { RealtimeMessage } from "@/lib/realtime";

interface Entry {
  key: string;
  at: string;
  title: string;
  price: unknown;
  detail: string;
}

const MAX = 30;
const COLUMNS = [
  ["LIVE DEALS", "deal.created"],
  ["TARGET HIT", "TARGET_PRICE_HIT"],
  ["RESTOCK", "RESTOCK"],
  ["PRICE DROP", "PRICE_DROP"],
] as const;

export default function WarRoom() {
  const now = useNow();
  const name = useProductNames();
  const status = useLoad(() => api.scannerStatus());
  const [lastScan, setLastScan] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, { status: string; at: string | null }>>({});
  const [feed, setFeed] = useState<Record<string, Entry[]>>({});
  const seq = useRef(0);

  const push = useCallback((column: string, entry: Omit<Entry, "key">) => {
    setFeed((f) => ({ ...f, [column]: [{ ...entry, key: String(seq.current++) }, ...(f[column] ?? [])].slice(0, MAX) }));
  }, []);

  const state = useRealtime(["deal.created", "alert.triggered", "scanner.status"], (m: RealtimeMessage) => {
    const at = m.ts ?? new Date().toISOString();
    const d = m.data;
    if (m.event === "scanner.status") {
      setLastScan(at);
      setHealth((h) => ({
        ...h,
        [d.retailer]: {
          status: d.status === "FAILED" ? "DEGRADED" : h[d.retailer]?.status && h[d.retailer].status !== "UNKNOWN" ? h[d.retailer].status : "ONLINE",
          at,
        },
      }));
      // authoritative health score comes from the server; refresh it after failures
      if (d.status === "FAILED") status.reload();
    } else if (m.event === "deal.created") {
      push("deal.created", { at, title: d.product ?? "Deal", price: d.price, detail: `${d.retailer} · score ${d.deal_score}` });
    } else if (m.event === "alert.triggered") {
      push(d.type, { at, title: name(d.product_id), price: d.price, detail: ALERT_LABEL[d.type] ?? d.type });
    }
  });

  // the server's health score is authoritative: re-sync every 30s so DEGRADED can recover
  useEffect(() => {
    const t = setInterval(() => status.reload(), 30_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const s = status.data;
    if (!s) return;
    setHealth(Object.fromEntries(s.retailers.map((r) => [r.code, { status: r.status, at: r.last_scan_at }])));
    setLastScan((cur) => cur ?? s.last_scan_at);
  }, [status.data]);

  const stale = lastScan !== null && now - Date.parse(lastScan) > 120_000;
  return (
    <>
      <div className="row between">
        <h1>Black Friday War Room</h1>
        <span className={`dot ${state}`}>{state === "open" ? "Live" : "Reconnecting…"}</span>
      </div>

      <section className="card health">
        <h2>Scanner Health</h2>
        {status.data?.retailers.map((r) => (
          <div className="row between" key={r.code}>
            <span>{r.name}</span>
            <span className={`status ${(health[r.code]?.status ?? r.status).toLowerCase()}`}>{health[r.code]?.status ?? r.status}</span>
          </div>
        ))}
        <p className={stale ? "error" : "muted"}>Last scan: {ago(lastScan, now)}</p>
      </section>

      <div className="grid4">
        {COLUMNS.map(([title, key]) => (
          <section key={key}>
            <h2>{title}</h2>
            {(feed[key] ?? []).length === 0 ? <p className="muted small">Waiting for activity…</p> : null}
            {(feed[key] ?? []).map((e) => (
              <article className="card compact" key={e.key}>
                <div className="title">{e.title}</div>
                <div className="row between">
                  <strong className="price">{money(e.price as number)}</strong>
                  <span className="muted small">{ago(e.at, now)}</span>
                </div>
                <div className="muted small">{e.detail}</div>
              </article>
            ))}
          </section>
        ))}
      </div>
    </>
  );
}
