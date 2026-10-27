"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";

function LoginForm() {
  const { me, signIn, signUp } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next") ?? "/dashboard";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me) router.replace(next.startsWith("/") ? next : "/dashboard");
  }, [me, next, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await signIn(email, password);
      else await signUp(email, password, name);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card auth">
      <h1>DealRadar</h1>
      <p className="muted">{mode === "login" ? "Sign in to your watchlist" : "Create an account"}</p>
      {mode === "register" ? (
        <input placeholder="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
      ) : null}
      <input type="email" required placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
      <input
        type="password"
        required
        minLength={8}
        placeholder="Password (8+ characters)"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        aria-label="Password"
      />
      {error ? <p className="error">{error}</p> : null}
      <button disabled={busy}>{mode === "login" ? "Sign in" : "Register"}</button>
      <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="center">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
