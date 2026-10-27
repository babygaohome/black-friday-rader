import type { HistoryPoint } from "@/lib/api";
import { money } from "@/lib/format";

const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"];
const W = 640;
const H = 220;
const PAD = { l: 52, r: 12, t: 12, b: 24 };

/** One line per offer (retailer). Plain SVG, no chart dependency. */
export function PriceChart({ points, labels }: { points: HistoryPoint[]; labels: Record<string, string> }) {
  const rows = points
    .map((p) => ({ ...p, t: Date.parse(p.timestamp), y: Number(p.effective_price) }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.y));
  if (rows.length < 2) return <p className="muted">Not enough price history yet.</p>;

  const t0 = Math.min(...rows.map((r) => r.t));
  const t1 = Math.max(...rows.map((r) => r.t));
  const lo = Math.min(...rows.map((r) => r.y));
  const hi = Math.max(...rows.map((r) => r.y));
  const span = hi - lo || 1;
  const x = (t: number) => PAD.l + ((t - t0) / (t1 - t0 || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);

  const byOffer = new Map<string, typeof rows>();
  for (const r of [...rows].sort((a, b) => a.t - b.t)) byOffer.set(r.offer_id, [...(byOffer.get(r.offer_id) ?? []), r]);
  const ids = [...byOffer.keys()];

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Price history">
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end" className="axis">
              {money(Math.round(v * 100) / 100)}
            </text>
          </g>
        ))}
        <text x={PAD.l} y={H - 6} className="axis">
          {new Date(t0).toLocaleDateString()}
        </text>
        <text x={W - PAD.r} y={H - 6} textAnchor="end" className="axis">
          {new Date(t1).toLocaleDateString()}
        </text>
        {ids.map((id, i) => (
          <polyline
            key={id}
            fill="none"
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            points={byOffer.get(id)!.map((r) => `${x(r.t)},${y(r.y)}`).join(" ")}
          />
        ))}
      </svg>
      <figcaption className="legend">
        {ids.map((id, i) => (
          <span key={id}>
            <i style={{ background: COLORS[i % COLORS.length] }} /> {labels[id] ?? "offer"}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
