const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "dealradar.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get(): string | null {
    try {
      return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null): void {
    try {
      if (token) window.localStorage.setItem(TOKEN_KEY, token);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable: the session just won't persist */
    }
  },
};

export function wsUrl(topics: string[] = []): string {
  const url = new URL(BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws";
  url.searchParams.set("token", tokenStore.get() ?? "");
  if (topics.length) url.searchParams.set("topics", topics.join(","));
  return url.toString();
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers, body });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : res.statusText;
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return data as T;
}

// ---- types (mirror the FastAPI responses) ----
export type Num = number | string | null;

export interface Deal {
  product_id: string;
  product: string;
  offer_id: string;
  retailer: string;
  url: string;
  price: Num;
  stock: string;
  deal_score: number;
  grade: string;
  verified: boolean;
  new_all_time_low: boolean;
  retailer_discount_pct: Num;
  actual_discount_pct: Num;
  normal_price: Num;
  discount_verdict: string;
  last_scanned_at: string | null;
}

export interface Alert {
  id: string;
  type: string;
  product_id: string;
  price: Num;
  previous_price: Num;
  deal_score: number | null;
  read: boolean;
  created_at: string;
}

export interface ProductRow {
  id: string;
  name: string;
  brand: string;
}

export interface ProductDetail {
  id: string;
  name: string;
  brand: string;
  best_price: Num;
  deal: {
    deal_score: number;
    grade: string;
    verified: boolean;
    new_all_time_low: boolean;
    retailer_discount_pct: Num;
    actual_discount_pct: Num;
    discount_verdict: string;
  } | null;
  metrics: { low_30d: Num; low_90d: Num; avg_30d: Num; all_time_low: Num } | null;
}

export interface OfferRow {
  id: string;
  retailer: string | null;
  url: string;
  title: string;
  price: Num;
  effective_price: Num;
  original_price: Num;
  stock: string;
  last_scanned_at: string | null;
}

export interface HistoryPoint {
  offer_id: string;
  effective_price: Num;
  stock: string;
  timestamp: string;
}

export interface WatchItem {
  id: string;
  product_id: string;
  target_price: Num;
  minimum_discount: Num;
  notify_on_stock: boolean;
  notify_on_historical_low: boolean;
  priority: string;
  active: boolean;
}

export interface Me {
  id: string;
  email: string;
  display_name: string;
  timezone: string;
  telegram_linked: boolean;
  is_admin: boolean;
}

export interface ScannerStatus {
  last_scan_at: string | null;
  retailers: { code: string; name: string; status: string; success_rate: Num; last_success: string | null; last_scan_at: string | null }[];
}

export const api = {
  login: (email: string, password: string) => request<{ token: string }>("/auth/login", { method: "POST", json: { email, password } }),
  register: (email: string, password: string, display_name = "") =>
    request<{ token: string }>("/auth/register", { method: "POST", json: { email, password, display_name } }),
  me: () => request<Me>("/users/me"),
  patchMe: (body: { display_name?: string; timezone?: string; telegram_chat_id?: string }) =>
    request<Me>("/users/me", { method: "PATCH", json: body }),
  products: (q = "", limit = 200) => request<ProductRow[]>(`/products?q=${encodeURIComponent(q)}&limit=${limit}`),
  product: (id: string) => request<ProductDetail>(`/products/${id}`),
  offers: (id: string) => request<OfferRow[]>(`/products/${id}/offers`),
  history: (id: string) => request<HistoryPoint[]>(`/products/${id}/history?limit=1000`),
  addFromUrl: (url: string) =>
    request<{ product_id: string; created: boolean }>("/products/from-url", { method: "POST", json: { url } }),
  watchlist: () => request<WatchItem[]>("/watchlist"),
  addWatch: (body: {
    product_id: string;
    target_price?: number | null;
    minimum_discount?: number | null;
    notify_on_stock?: boolean;
    notify_on_historical_low?: boolean;
  }) => request<WatchItem>("/watchlist", { method: "POST", json: body }),
  patchWatch: (id: string, body: Partial<Pick<WatchItem, "target_price" | "minimum_discount" | "notify_on_stock" | "notify_on_historical_low" | "priority">>) =>
    request<WatchItem>(`/watchlist/${id}`, { method: "PATCH", json: body }),
  deleteWatch: (id: string) => request<void>(`/watchlist/${id}`, { method: "DELETE" }),
  alerts: (limit = 100) => request<Alert[]>(`/alerts?limit=${limit}`),
  markRead: (id: string) => request<void>(`/alerts/${id}/read`, { method: "POST" }),
  deals: (minScore = 50, limit = 100) => request<Deal[]>(`/deals?min_score=${minScore}&limit=${limit}`),
  hotDeals: (limit = 100) => request<Deal[]>(`/deals/hot?limit=${limit}`),
  latestDeals: (limit = 50) => request<Deal[]>(`/deals/latest?limit=${limit}`),
  scannerStatus: () => request<ScannerStatus>("/scanner/status"),
};
