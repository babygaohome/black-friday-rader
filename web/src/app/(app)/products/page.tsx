"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/hooks";

const PAGE = 24;

export default function Products() {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(0);
  // wait for a pause in typing before querying
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(text);
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [text]);
  const categories = useLoad(() => api.categories(), []);
  const rows = useLoad(() => api.searchProducts(q, category, PAGE + 1, page * PAGE), [q, category, page]);
  const shown = rows.data?.slice(0, PAGE) ?? [];
  const names = Object.fromEntries((categories.data ?? []).map((c) => [c.slug, c.name]));
  return (
    <>
      <h1>Products</h1>
      <input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search tracked products, e.g. sony headphones"
        aria-label="Search products"
      />
      <div className="chips" role="group" aria-label="Category">
        <button className={category === "" ? "chip active" : "chip"} onClick={() => (setCategory(""), setPage(0))}>
          All
        </button>
        {categories.data?.map((c) => (
          <button
            key={c.slug}
            className={category === c.slug ? "chip active" : "chip"}
            onClick={() => (setCategory(c.slug), setPage(0))}
          >
            {c.name} ({c.count})
          </button>
        ))}
      </div>
      {rows.error ? <p className="error">{rows.error}</p> : null}
      {!rows.loading && shown.length === 0 ? <p className="muted">No products match. Add one from the Dashboard by pasting its link.</p> : null}
      <div className="grid2">
        {shown.map((p) => (
          <article key={p.id} className="card">
            <Link href={`/products/${p.id}`} className="title">
              {p.name}
            </Link>
            <div className="row between">
              <strong className="price">{money(p.best_price)}</strong>
              <span className="muted small">
                {p.offer_count} {p.offer_count === 1 ? "retailer" : "retailers"}
              </span>
            </div>
            {p.category ? <div className="small muted">{names[p.category] ?? p.category}</div> : null}
          </article>
        ))}
      </div>
      <div className="row">
        <button disabled={page === 0} onClick={() => setPage(page - 1)}>
          Previous
        </button>
        <button disabled={(rows.data?.length ?? 0) <= PAGE} onClick={() => setPage(page + 1)}>
          Next
        </button>
      </div>
    </>
  );
}
