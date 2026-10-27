"use client";
import Link from "next/link";
import { AddProduct } from "@/components/AddProduct";
import { DealCard } from "@/components/DealCard";
import { api, type Alert } from "@/lib/api";
import { ALERT_LABEL, ago, money } from "@/lib/format";
import { useLoad, useNow, useProductNames, useRealtime } from "@/lib/hooks";

function AlertList({ title, alerts, empty }: { title: string; alerts: Alert[]; empty: string }) {
  const name = useProductNames();
  const now = useNow(15_000);
  return (
    <section>
      <h2>{title}</h2>
      {alerts.length === 0 ? <p className="muted">{empty}</p> : null}
      {alerts.slice(0, 6).map((a) => (
        <article className="card" key={a.id}>
          <div className="row between">
            <Link href={`/products/${a.product_id}`} className="title">
              {name(a.product_id)}
            </Link>
            <span className="tag">{ALERT_LABEL[a.type] ?? a.type}</span>
          </div>
          <div className="row between">
            <strong className="price">{money(a.price)}</strong>
            <span className="muted small">
              {a.previous_price !== null ? `was ${money(a.previous_price)} · ` : ""}
              {ago(a.created_at, now)}
            </span>
          </div>
        </article>
      ))}
    </section>
  );
}

export default function Dashboard() {
  const hot = useLoad(() => api.hotDeals(12));
  const latest = useLoad(() => api.latestDeals(50));
  const alerts = useLoad(() => api.alerts(100));
  const live = useRealtime(["deal.created", "alert.triggered", "price.updated"], () => {
    hot.reload();
    latest.reload();
    alerts.reload();
  });

  const drops = [...(latest.data ?? [])]
    .filter((d) => Number(d.actual_discount_pct) > 0)
    .sort((a, b) => Number(b.actual_discount_pct) - Number(a.actual_discount_pct))
    .slice(0, 6);
  const all = alerts.data ?? [];

  return (
    <>
      <div className="row between">
        <h1>Dashboard</h1>
        <span className={`dot ${live}`} title={`Live updates: ${live}`}>
          {live === "open" ? "Live" : "Reconnecting…"}
        </span>
      </div>
      <AddProduct />
      <div className="grid2">
        <section>
          <h2>🔥 Hot Deals</h2>
          {hot.error ? <p className="error">{hot.error}</p> : null}
          {hot.data?.length === 0 ? <p className="muted">No hot deals right now.</p> : null}
          {hot.data?.map((d) => <DealCard key={d.offer_id} deal={d} />)}
        </section>
        <section>
          <h2>📉 Biggest Drops</h2>
          {drops.length === 0 ? <p className="muted">No drops against the 30-day price yet.</p> : null}
          {drops.map((d) => <DealCard key={d.offer_id} deal={d} />)}
        </section>
        <AlertList title="🎯 Target Hits" alerts={all.filter((a) => a.type === "TARGET_PRICE_HIT")} empty="None of your targets have been hit." />
        <AlertList title="📦 Restocks" alerts={all.filter((a) => a.type === "RESTOCK")} empty="No restocks on your watchlist." />
      </div>
    </>
  );
}
