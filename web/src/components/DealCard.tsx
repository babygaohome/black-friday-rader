import Link from "next/link";
import type { Deal } from "@/lib/api";
import { VERDICT_LABEL, ago, money, pct, stockLabel } from "@/lib/format";
import { ScoreBadge } from "./ScoreBadge";

export function DealCard({ deal, now }: { deal: Deal; now?: number }) {
  const real = deal.actual_discount_pct;
  const claimed = deal.retailer_discount_pct;
  return (
    <article className="card">
      <div className="row between">
        <Link href={`/products/${deal.product_id}`} className="title">
          {deal.product}
        </Link>
        <ScoreBadge score={deal.deal_score} grade={deal.grade} verified={deal.verified} />
      </div>
      <div className="row between">
        <strong className="price">{money(deal.price)}</strong>
        <span className="muted">{deal.retailer}</span>
      </div>
      <div className="muted small">
        {real !== null && real !== undefined ? `${pct(real)} below the 30-day price` : "No price history yet"}
        {claimed !== null && claimed !== undefined ? ` · retailer claims ${pct(claimed)} off` : ""}
      </div>
      <div className="small">
        <span className={`verdict ${deal.discount_verdict.toLowerCase()}`}>{VERDICT_LABEL[deal.discount_verdict] ?? deal.discount_verdict}</span>
        {deal.new_all_time_low ? <span className="tag">all-time low</span> : null}
        <span className="muted"> · {stockLabel(deal.stock)} · scanned {ago(deal.last_scanned_at, now)}</span>
      </div>
    </article>
  );
}
