"use client";
import { useState } from "react";
import { DealCard } from "@/components/DealCard";
import { api } from "@/lib/api";
import { useLoad, useNow, useRealtime } from "@/lib/hooks";

const LEVELS = [
  [85, "Hot (85+)"],
  [70, "Good (70+)"],
  [50, "Worth a look (50+)"],
] as const;

export default function Deals() {
  const [min, setMin] = useState(70);
  const deals = useLoad(() => api.deals(min, 100), [min]);
  const now = useNow(15_000);
  useRealtime(["deal.created"], () => deals.reload());
  return (
    <>
      <div className="row between">
        <h1>Deals</h1>
        <select value={min} onChange={(e) => setMin(Number(e.target.value))} aria-label="Minimum score">
          {LEVELS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {deals.error ? <p className="error">{deals.error}</p> : null}
      {deals.data?.length === 0 ? <p className="muted">No deals at this level.</p> : null}
      <div className="grid2">{deals.data?.map((d) => <DealCard key={d.offer_id} deal={d} now={now} />)}</div>
    </>
  );
}
