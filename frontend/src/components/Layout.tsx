import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { ROLE_LABEL, useAuth } from "../lib/auth";
import { BRAND, BRAND_LONG } from "../lib/brand";

type Item = { to: string; label: string; end?: boolean };
const NAV: Record<string, Item[]> = {
  AICTE_ADMIN: [
    { to: "/aicte", label: "Overview", end: true },
    { to: "/aicte/institutions", label: "Institutions" },
    { to: "/aicte/anomalies", label: "Anomalies" },
    { to: "/aicte/conflicts", label: "Duplicate enrolments" },
    { to: "/aicte/audit", label: "Audit log" },
    { to: "/aicte/system", label: "Administration" },
  ],
  INSTITUTION_ADMIN: [
    { to: "/institution", label: "Overview", end: true },
    { to: "/institution/students", label: "Students" },
    { to: "/institution/upload", label: "Upload" },
    { to: "/institution/add", label: "Add student" },
    { to: "/institution/issues", label: "Corrections" },
    { to: "/institution/conflicts", label: "Duplicate enrolments" },
    { to: "/institution/requests", label: "Requests" },
    { to: "/institution/integration", label: "Integration" },
  ],
  STUDENT: [
    { to: "/student", label: "My record", end: true },
    { to: "/student/wallet", label: "Credentials" },
    { to: "/student/access", label: "Access history" },
  ],
  REGULATOR: [{ to: "/regulator", label: "Audit queries", end: true }, { to: "/regulator/chain", label: "Audit log" }],
  UNIVERSITY_REGISTRAR: [{ to: "/university", label: "Degrees", end: true }],
};
NAV.DATA_OPERATOR = NAV.INSTITUTION_ADMIN.filter((i) => !["/institution/integration", "/institution/requests"].includes(i.to));

export function Wordmark({ light = true }: { light?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="4" fill={light ? "white" : "#0f3e7a"} />
        <rect x="9" y="8" width="3" height="16" fill={light ? "#0f3e7a" : "white"} />
        <rect x="15" y="8" width="8" height="3" fill={light ? "#0f3e7a" : "white"} />
        <rect x="15" y="14.5" width="8" height="3" fill={light ? "#0f3e7a" : "white"} />
        <rect x="15" y="21" width="8" height="3" fill={light ? "#0f3e7a" : "white"} />
      </svg>
      <span className={`text-[15px] font-semibold tracking-[-0.01em] ${light ? "text-white" : "text-ink-900"}`}>{BRAND}</span>
    </span>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  if (!user) return null;
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded px-2 py-1 text-left text-white hover:bg-white/10">
        <span className="hidden text-right leading-tight sm:block">
          <span className="block text-[13px] font-medium">{user.display_name}</span>
          <span className="block text-2xs text-brand-100">{ROLE_LABEL[user.role]}</span>
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-full bg-white/15 text-xs font-semibold">
          {user.display_name.split(/[ ,]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}</span>
        <ChevronDown className="h-3.5 w-3.5 text-brand-100" />
      </button>
      {open && (
        <div className="panel absolute right-0 z-40 mt-1 w-64 py-1 text-sm shadow-lg">
          <div className="border-b border-ink-100 px-3 py-2">
            <div className="font-medium text-ink-900">{user.display_name}</div>
            <div className="text-xs text-ink-500">{user.username} · {ROLE_LABEL[user.role]}{user.mfa_enabled ? " · 2-step verification on" : ""}</div>
          </div>
          <a className="block px-3 py-2 text-ink-700 hover:bg-ink-50" href="/verify" target="_blank" rel="noreferrer">Credential verifier</a>
          {user.role !== "STUDENT" && <a className="block px-3 py-2 text-ink-700 hover:bg-ink-50" href="/docs" target="_blank" rel="noreferrer">API documentation</a>}
          <button className="block w-full px-3 py-2 text-left text-ink-700 hover:bg-ink-50" onClick={() => { signOut(); nav("/login"); }}>Sign out</button>
        </div>)}
    </div>
  );
}

export default function Layout() {
  const { user } = useAuth();
  const items = NAV[user?.role ?? ""] ?? [];
  const org = user?.institution?.name ?? user?.university?.name ??
    (user?.regulator_body ? `${user.regulator_body}` : user?.role === "AICTE_ADMIN" ? "AICTE" : null);
  return (
    <div className="flex min-h-screen flex-col">
      <div className="bg-ink-900 text-2xs text-ink-300">
        <div className="container-app flex h-7 items-center justify-between">
          <span>{BRAND_LONG}</span>
          <span>Prototype · synthetic data</span>
        </div>
      </div>
      <header className="bg-brand-700">
        <div className="container-app flex h-14 items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <Wordmark />
            {org && <span className="hidden min-w-0 truncate border-l border-white/25 pl-4 text-[13px] text-brand-100 md:block">{org}</span>}
          </div>
          <UserMenu />
        </div>
      </header>
      <nav className="border-b border-ink-200 bg-white">
        <div className="container-app flex gap-6 overflow-x-auto">
          {items.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.end}
              className={({ isActive }) => `-mb-px whitespace-nowrap border-b-[3px] py-3 text-sm font-medium ${isActive ? "border-brand-700 text-ink-900" : "border-transparent text-ink-600 hover:text-ink-900"}`}>
              {i.label}
            </NavLink>
          ))}
        </div>
      </nav>
      <main className="container-app flex-1 py-7"><Outlet /></main>
      <footer className="border-t border-ink-200 bg-white">
        <div className="container-app flex flex-wrap justify-between gap-2 py-4 text-xs text-ink-500">
          <span>{BRAND} · {BRAND_LONG}</span>
          <span>APAAR registry, DigiLocker and the AICTE approval feed are simulated in this prototype.</span>
        </div>
      </footer>
    </div>
  );
}
