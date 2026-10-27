"use client";
import { use, useState } from "react";
import { PriceChart } from "@/components/PriceChart";
import { ScoreBadge } from "@/components/ScoreBadge";
import { api } from "@/lib/api";
import { VERDICT_LABEL, ago, money, pct, stockLabel } from "@/lib/format";
import { useLoad, useRealtime } from "@/lib/hooks";

export default function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const product = useLoad(() => api.product(id), [id]);
  const offers = useLoad(() => api.offers(id), [id]);
  const history = useLoad(() => api.history(id), [id]);
  const watches = useLoad(() => api.watchlist());
  const [target, setTarget] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useRealtime(["price.updated", "stock.updated"], (m) => {
    if (m.data.product_id === id) {
      product.reload();
      offers.reload();
      history.reload();
    }
  });

  const watch = watches.data?.find((w) => w.product_id === id);
  const labels = Object.fromEntries((offers.data ?? []).map((o) => [o.id, o.retailer ?? "offer"]));
  const p = product.data;

  async function track() {
    setMessage(null);
    try {
      await api.addWatch({ product_id: id, target_price: target.trim() === "" ? null : Number(target), notify_on_stock: true, notify_on_historical_low: true });
      setMessage("Now tracking this product.");
      watches.reload();
    } catch (e) {
      setMessage((e as Error).message);
    }
  }

  if (product.error) return <p className="error">{product.error}</p>;
  if (!p) return <p className="muted">Loading…</p>;
  return (
    <>
      <h1>{p.name}</h1>
      <div className="stats">
        <div>
          <span className="muted small">Current best</span>
          <strong className="price">{money(p.best_price)}</strong>
        </div>
        <div>
          <span className="muted small">90-day low</span>
          <strong>{money(p.metrics?.low_90d)}</strong>
        </div>
        <div>
          <span className="muted small">All-time low</span>
          <strong>{money(p.metrics?.all_time_low)}</strong>
        </div>
        <div>
          <span className="muted small">30-day average</span>
          <strong>{money(p.metrics?.avg_30d)}</strong>
        </div>
      </div>

      {p.deal ? (
        <div className="card">
          <div className="row between">
            <ScoreBadge score={p.deal.deal_score} grade={p.deal.grade} verified={p.deal.verified} />
            <span className={`verdict ${p.deal.discount_verdict.toLowerCase()}`}>{VERDICT_LABEL[p.deal.discount_verdict] ?? p.deal.discount_verdict}</span>
          </div>
          <p className="muted small">
            {p.deal.actual_discount_pct !== null ? `${pct(p.deal.actual_discount_pct)} below the 30-day price` : "No price history to compare yet"}
            {p.deal.retailer_discount_pct !== null ? ` · retailer claims ${pct(p.deal.retailer_discount_pct)} off` : ""}
          </p>
        </div>
      ) : null}

      <h2>Retailers</h2>
      <table className="table">
        <tbody>
          {offers.data?.map((o) => (
            <tr key={o.id}>
              <td>
                <a href={o.url} target="_blank" rel="noopener noreferrer">
                  {o.retailer}
                </a>
              </td>
              <td className="num">
                <strong>{money(o.effective_price)}</strong>
              </td>
              <td className="muted small">{stockLabel(o.stock)}</td>
              <td className="muted small">scanned {ago(o.last_scanned_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Price history</h2>
      <PriceChart points={history.data ?? []} labels={labels} />

      <h2>Alerts</h2>
      {watch ? (
        <p>
          Tracking · target {watch.target_price !== null ? money(watch.target_price) : "none"}.{" "}
          <button
            className="link"
            onClick={async () => {
              await api.deleteWatch(watch.id);
              watches.reload();
            }}
          >
            Stop tracking
          </button>
        </p>
      ) : (
        <div className="row gap">
          <input className="narrow" inputMode="decimal" placeholder="Target price" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Target price" />
          <button onClick={track}>Track</button>
        </div>
      )}
      {message ? <p className="muted">{message}</p> : null}
    </>
  );
}
