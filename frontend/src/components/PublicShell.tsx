import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Wordmark } from "./Layout";
import { BRAND, BRAND_LONG } from "../lib/brand";

/** Chrome for pages used without signing in (sign-in, verifier). */
export default function PublicShell({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <div className="bg-ink-900 text-2xs text-ink-300">
        <div className="container-app flex h-7 items-center justify-between"><span>{BRAND_LONG}</span><span>Prototype · synthetic data</span></div>
      </div>
      <header className="bg-brand-700">
        <div className="container-app flex h-14 items-center justify-between">
          <Link to="/" className="no-underline"><Wordmark /></Link>
          <div className="flex items-center gap-4 text-[13px] text-white">{right}</div>
        </div>
      </header>
      <main className="container-app flex-1 py-8">{children}</main>
      <footer className="border-t border-ink-200 bg-white">
        <div className="container-app py-4 text-xs text-ink-500">{BRAND} · {BRAND_LONG}</div>
      </footer>
    </div>
  );
}
