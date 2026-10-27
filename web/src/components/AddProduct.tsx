"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export function AddProduct() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { product_id } = await api.addFromUrl(url.trim());
      router.push(`/products/${product_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="row gap add">
      <input
        type="url"
        required
        placeholder="Paste a product link (JB Hi-Fi, Officeworks, Good Guys, Harvey Norman, Amazon AU)"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="Product URL"
      />
      <button disabled={busy}>{busy ? "Adding…" : "Track product"}</button>
      {error ? <span className="error">{error}</span> : null}
    </form>
  );
}
