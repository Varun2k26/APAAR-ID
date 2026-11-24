import { X } from "lucide-react";
import { Link } from "react-router-dom";
import { useCallback, useEffect, useState, type ReactNode } from "react";

/* ------------------------------------------------------------------ data helpers */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(async () => {
    setLoading(true);
    try { setData(await fn()); setError(null); }
    catch (e: any) { setError(e.message || String(e)); }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run, setData };
}

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-IN"));
export const pct = (n: number | null | undefined, d = 0) => (n == null ? "—" : `${(n * 100).toFixed(d)}%`);
export const when = (s?: string | null) => (s ? new Date(s.endsWith("Z") ? s : s + "Z").toLocaleString("en-IN",
  { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
export const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—");
export const humanize = (s: string) => {
  const t = String(s).replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, description, actions, crumbs, meta }:
  { title: ReactNode; description?: ReactNode; actions?: ReactNode; crumbs?: { label: string; to?: string }[]; meta?: ReactNode }) {
  return (
    <div className="mb-6">
      {crumbs && (
        <nav className="mb-2 flex flex-wrap items-center gap-1.5 text-[13px] text-ink-500">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {c.to ? <Link className="link" to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
              {i < crumbs.length - 1 && <span className="text-ink-300">/</span>}
            </span>))}
        </nav>)}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold leading-7 tracking-[-0.01em] text-ink-900">{title}</h1>
          {description && <p className="mt-1 max-w-3xl text-sm text-ink-500">{description}</p>}
          {meta && <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-500">{meta}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Panel({ title, description, actions, children, className = "", flush = false }:
  { title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-200 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-ink-900">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-ink-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export type StatItem = { label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "bad" | "warn" | "good" };
export function Stats({ items }: { items: StatItem[] }) {
  const tone = { default: "text-ink-900", bad: "text-red-700", warn: "text-amber-700", good: "text-emerald-700" };
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-ink-200 bg-ink-200 sm:grid-cols-3 lg:flex [&>*:last-child:nth-child(odd)]:col-span-2 sm:[&>*:last-child:nth-child(odd)]:col-span-1">
      {items.map((s, i) => (
        <div key={i} className="min-w-0 flex-1 bg-white px-4 py-3.5">
          <div className="text-[13px] text-ink-500">{s.label}</div>
          <div className={`mt-1 text-[26px] font-semibold leading-8 tabular ${tone[s.tone ?? "default"]}`}>{s.value}</div>
          {s.sub && <div className="mt-0.5 text-xs text-ink-500">{s.sub}</div>}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ status */
const TONES = {
  red: "border-red-200 bg-red-50 text-red-800",
  amber: "border-amber-200 bg-amber-50 text-amber-800",
  green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  blue: "border-brand-200 bg-brand-50 text-brand-800",
  grey: "border-ink-200 bg-ink-50 text-ink-700",
};
const STATUS_TONE: Record<string, keyof typeof TONES> = {
  ACTIVE: "green", VERIFIED: "green", APPROVED: "green", RESOLVED: "green", DELIVERED: "green", CREATED: "green",
  COMPLETED: "green", ACCEPTED: "green", VALID: "green", OK: "green",
  CONFLICT: "red", REJECTED: "red", ERROR: "red", HIGH: "red", DENIED: "red", VOID: "red", FAILED: "red",
  REVOKED: "red", CONFIRMED: "red", EXACT: "red", INVALID: "red",
  WARN: "amber", WARNING: "amber", MEDIUM: "amber", PENDING: "amber", OPEN: "amber", PROVISIONAL: "amber",
  SUSPENDED: "amber", PENDING_STUDENT: "amber", PENDING_RELEASE: "amber", FUZZY: "amber", EXPIRED: "grey",
  INVESTIGATING: "blue", STUDENT_CONFIRMED: "blue", INFO: "blue", UPDATED: "blue", STATISTICAL: "blue", GRADUATED: "blue",
  DISMISSED: "grey", DROPPED: "grey", TRANSFERRED_OUT: "grey", EXEMPT: "grey", UNCHANGED: "grey", RULE: "grey", LOW: "grey",
};
const LABEL_OVERRIDE: Record<string, string> = {
  EXACT: "Same APAAR", FUZZY: "Probable match", WARN: "Warning", PENDING_STUDENT: "Awaiting student",
  PENDING_RELEASE: "Awaiting release", STUDENT_CONFIRMED: "Student responded", STATISTICAL: "Statistical", RULE: "Rule",
};

export function Tag({ children, tone, title }: { children: ReactNode; tone?: keyof typeof TONES; title?: string }) {
  return <span title={title} className={`inline-flex h-5 items-center whitespace-nowrap rounded-sm border px-1.5 text-xs font-medium ${TONES[tone ?? "grey"]}`}>{children}</span>;
}

/** Status tag from a backend enum value, e.g. "TRANSFERRED_OUT" -> "Transferred out". */
export function Status({ s, label }: { s: string; label?: string }) {
  const k = String(s ?? "");
  return <Tag tone={STATUS_TONE[k] ?? "grey"}>{label ?? LABEL_OVERRIDE[k] ?? humanize(k)}</Tag>;
}

export function Code({ c, severity }: { c: string; severity?: string }) {
  const tone = severity === "ERROR" ? "text-red-700" : severity === "WARN" ? "text-amber-700" : "text-ink-600";
  return <span className={`mono font-medium ${tone}`}>{c}</span>;
}

/* ------------------------------------------------------------------ feedback */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="px-4 py-8 text-sm text-ink-500">{label}</div>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-8 text-sm text-ink-500">{children}</div>;
}
export function Alert({ tone = "info", title, children, className = "" }:
  { tone?: "info" | "warn" | "error" | "success"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const c = { info: "border-l-brand-600 bg-brand-50/60", warn: "border-l-amber-600 bg-amber-50", error: "border-l-red-700 bg-red-50",
              success: "border-l-emerald-700 bg-emerald-50" }[tone];
  return (
    <div className={`rounded-sm border border-ink-200 border-l-4 px-4 py-3 text-sm ${c} ${className}`}>
      {title && <div className="font-semibold text-ink-900">{title}</div>}
      {children && <div className={`text-ink-700 ${title ? "mt-0.5" : ""}`}>{children}</div>}
    </div>
  );
}
export function ErrorText({ error }: { error: string | null }) {
  return error ? <Alert tone="error">{error}</Alert> : null;
}

export function useToast() {
  const [msg, setMsg] = useState<{ text: string; tone: "good" | "bad" } | null>(null);
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(null), 3500); return () => clearTimeout(t); } }, [msg]);
  const node = msg ? (
    <div role="status" className={`fixed bottom-5 right-5 z-50 max-w-sm rounded border-l-4 bg-ink-900 px-4 py-2.5 text-sm text-white shadow-lg ${msg.tone === "good" ? "border-l-emerald-400" : "border-l-red-400"}`}>{msg.text}</div>
  ) : null;
  return { toast: (text: string, tone: "good" | "bad" = "good") => setMsg({ text, tone }), node };
}

/* ------------------------------------------------------------------ overlays & navigation */
export function Modal({ open, onClose, title, children, wide, footer }:
  { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-900/40 p-4 pt-[8vh]" onClick={onClose}>
      <div role="dialog" aria-modal className={`panel w-full shadow-xl ${wide ? "max-w-3xl" : "max-w-lg"}`} onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <button className="rounded p-1 text-ink-500 hover:bg-ink-100 hover:text-ink-800" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button>
        </header>
        <div className="max-h-[72vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-ink-200 bg-ink-50 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: ReactNode; count?: number }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="mb-4 flex gap-6 overflow-x-auto border-b border-ink-200">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`-mb-px whitespace-nowrap border-b-2 pb-2.5 pt-1 text-sm font-medium ${active === t.id ? "border-brand-700 text-ink-900" : "border-transparent text-ink-500 hover:text-ink-800"}`}>
          {t.label}{t.count != null && <span className="ml-1.5 rounded-sm bg-ink-100 px-1.5 py-px text-xs text-ink-600 tabular">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented({ options, value, onChange }: { options: { id: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded border border-ink-300 bg-white p-0.5">
      {options.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)}
          className={`rounded-sm px-2.5 py-1 text-[13px] ${value === o.id ? "bg-brand-700 text-white" : "text-ink-600 hover:bg-ink-50"}`}>{o.label}</button>
      ))}
    </div>
  );
}

export function DL({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-ink-100 text-sm">
      {rows.map(([k, v], i) => (
        <div key={i} className="grid grid-cols-[minmax(120px,40%)_1fr] gap-3 py-2">
          <dt className="text-ink-500">{k}</dt><dd className="min-w-0 break-words text-ink-900">{v ?? "—"}</dd>
        </div>))}
    </dl>
  );
}

export function Findings({ findings }: { findings: { code: string; severity: string; message: string; hint?: string | null }[] }) {
  if (!findings?.length) return null;
  return (
    <ul className="space-y-1.5">
      {findings.map((f, i) => (
        <li key={i} className="grid grid-cols-[44px_1fr] gap-2 text-[13px]">
          <Code c={f.code} severity={f.severity} />
          <div><span className="text-ink-800">{f.message}</span>{f.hint && <div className="text-ink-500">{f.hint}</div>}</div>
        </li>
      ))}
    </ul>
  );
}

export function Pager({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const last = Math.max(1, Math.ceil(total / size));
  return (
    <div className="flex items-center justify-between border-t border-ink-200 px-4 py-2.5 text-[13px] text-ink-500">
      <span className="tabular">{total ? `${fmt((page - 1) * size + 1)}–${fmt(Math.min(page * size, total))} of ${fmt(total)}` : "No records"}</span>
      <div className="flex gap-2">
        <button className="btn-secondary btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button className="btn-secondary btn-sm" disabled={page >= last} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}
