"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AddProduct } from "@/components/AddProduct";
import { api, type ProductDetail, type WatchItem } from "@/lib/api";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/hooks";

function Row({ item, onChange }: { item: WatchItem; onChange: () => void }) {
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [target, setTarget] = useState(item.target_price === null ? "" : String(item.target_price));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.product(item.product_id).then(setProduct).catch(() => {});
  }, [item.product_id]);

  async function save() {
    setError(null);
    try {
      await api.patchWatch(item.id, { target_price: target.trim() === "" ? null : Number(target) });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const hit = product?.best_price != null && item.target_price != null && Number(product.best_price) <= Number(item.target_price);
  return (
    <tr>
      <td>
        <Link href={`/products/${item.product_id}`}>{product?.name ?? "…"}</Link>
      </td>
      <td className="num">{money(product?.best_price)}</td>
      <td className="num">
        <input
          className="narrow"
          inputMode="decimal"
          placeholder="none"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onBlur={save}
          aria-label={`Target price for ${product?.name ?? "product"}`}
        />
        {hit ? <span className="tag">hit</span> : null}
        {error ? <span className="error"> {error}</span> : null}
      </td>
      <td>
        <button
          className="link"
          onClick={async () => {
            await api.deleteWatch(item.id);
            onChange();
          }}
        >
          Remove
        </button>
      </td>
    </tr>
  );
}

export default function Watchlist() {
  const list = useLoad(() => api.watchlist());
  return (
    <>
      <h1>Watchlist</h1>
      <AddProduct />
      {list.error ? <p className="error">{list.error}</p> : null}
      {list.data?.length === 0 ? <p className="muted">Nothing watched yet. Paste a product link above, then set a target price on its page.</p> : null}
      {list.data?.length ? (
        <table className="table">
          <thead>
            <tr>
              <th>Product</th>
              <th className="num">Best price</th>
              <th className="num">Target</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.data.map((w) => (
              <Row key={w.id} item={w} onChange={list.reload} />
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}
