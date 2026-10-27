"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  ["/dashboard", "Dashboard"],
  ["/watchlist", "Watchlist"],
  ["/deals", "Deals"],
  ["/war-room", "War Room"],
  ["/settings", "Settings"],
] as const;

export function Nav() {
  const path = usePathname();
  const { me, signOut } = useAuth();
  return (
    <nav className="nav">
      <strong className="brand">DealRadar</strong>
      {LINKS.map(([href, label]) => (
        <Link key={href} href={href} className={path.startsWith(href) ? "active" : ""}>
          {label}
        </Link>
      ))}
      <span className="spacer" />
      <span className="muted small">{me?.email}</span>
      <button className="link" onClick={signOut}>
        Sign out
      </button>
    </nav>
  );
}
