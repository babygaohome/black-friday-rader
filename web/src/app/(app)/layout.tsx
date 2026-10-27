import type { ReactNode } from "react";
import { Nav } from "@/components/Nav";
import { RequireAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <Nav />
      <main className="page">{children}</main>
    </RequireAuth>
  );
}
