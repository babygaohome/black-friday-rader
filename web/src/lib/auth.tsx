"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, tokenStore, type Me } from "@/lib/api";

interface AuthState {
  me: Me | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    if (!tokenStore.get()) {
      setMe(null);
      setReady(true);
      return;
    }
    try {
      setMe(await api.me());
    } catch {
      tokenStore.set(null);
      setMe(null);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const signIn = async (email: string, password: string) => {
    tokenStore.set((await api.login(email, password)).token);
    await load();
  };
  const signUp = async (email: string, password: string, name: string) => {
    tokenStore.set((await api.register(email, password, name)).token);
    await load();
  };
  const signOut = () => {
    tokenStore.set(null);
    setMe(null);
  };

  return <Ctx.Provider value={{ me, ready, signIn, signUp, signOut }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** Wrap a page: redirects to /login when signed out. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, ready } = useAuth();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (ready && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [ready, me, router, path]);
  if (!ready || !me) return <p className="muted pad">Loading…</p>;
  return <>{children}</>;
}
