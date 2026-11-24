import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../lib/api";
import { EVENT_LABEL, useLiveEvents, type SpineEvent } from "../../lib/live";
import { ErrorText, fmt, Loading, PageHeader, Panel, pct, Segmented, Stats, Status, useAsync, when, day } from "../../components/ui";
import IndiaTiles, { STATE_NAME } from "../../components/IndiaTiles";

const CAT_LABEL: Record<string, string> = { GEN: "General", EWS: "EWS", "OBC-NCL": "OBC (NCL)", SC: "SC", ST: "ST" };
const AXIS = { fontSize: 12, fill: "#5f6873", fontFamily: "IBM Plex Sans" };

export default function Overview() {
  const nav = useNavigate();
  const nat = useAsync(() => api.get("/api/v1/analytics/national"), []);
  const meta = useAsync(() => api.get("/api/v1/meta"), []);
  const anomalies = useAsync(() => api.get("/api/v1/anomalies?status=OPEN&limit=8"), []);
  const recent = useAsync(() => api.get<SpineEvent[]>("/api/v1/events/recent?limit=25&types=CONFLICT_OPENED,ANOMALY_RAISED,INTAKE_ALERT,SUBMISSION_PROCESSED,CONFLICT_RESOLVED,CONFLICT_STUDENT_CONFIRMED"), []);
  const [feed, setFeed] = useState<SpineEvent[]>([]);
  const [metric, setMetric] = useState<"students" | "fill" | "anomalies">("students");
  const live = useLiveEvents((e) => {
    if (["ENROLLMENT_CREATED", "ISSUE_RAISED", "ENROLLMENT_UPDATED"].includes(e.type)) return;
    setFeed((f) => [e, ...f].slice(0, 40));
    if (["SUBMISSION_PROCESSED", "CONFLICT_OPENED", "ANOMALY_RAISED", "INTAKE_ALERT", "CONFLICT_RESOLVED"].includes(e.type)) { nat.reload(); anomalies.reload(); }
  });
  if (nat.loading && !nat.data) return <Loading />;
  if (nat.error) return <ErrorText error={nat.error} />;
  const d = nat.data, k = d.kpis, m = meta.data;
  const events = [...feed, ...(recent.data ?? []).filter((r) => !feed.some((f) => f.id === r.id))].slice(0, 30);
  const conf = (k.open_conflicts.EXACT ?? 0) + (k.open_conflicts.FUZZY ?? 0);
  const catTotal = Object.values(d.categories as Record<string, number>).reduce((a, b) => a + b, 0) || 1;
  const peak = Math.max(...d.trend.map((t: any) => Math.max(t.admitted, t.approved)), 1);
  const step = peak > 40000 ? 20000 : peak > 20000 ? 10000 : 5000;
  const yMax = Math.ceil(peak / step) * step;
  const yTicks = Array.from({ length: yMax / step + 1 }, (_, i) => i * step);

  return (
    <div className="space-y-6">
      <PageHeader title="National overview"
        meta={m && <>
          <span>Academic year {m.label}</span>
          <span>Admissions close {day(m.admission_cutoff)}</span>
          <span>Census {day(m.census_date)}</span>
          <span className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${live ? "bg-emerald-600" : "bg-ink-300"}`} />{live ? "Live" : "Connecting"}</span>
        </>} />

      <Stats items={[
        { label: "Students reported", value: fmt(k.students), sub: `${k.reporting_institutions} of ${k.institutions} institutions reporting` },
        { label: "Seat utilisation", value: pct(k.utilisation, 1), sub: `${fmt(k.regular)} of ${fmt(k.approved_intake)} approved seats` },
        { label: "APAAR coverage", value: pct(k.apaar_coverage, 1), sub: `${fmt(k.provisional)} on provisional IDs`, tone: k.apaar_coverage < 0.97 ? "warn" : "default" },
        { label: "Supernumerary", value: fmt(k.supernumerary), sub: "TFW, FN/OCI/PIO, lateral entry" },
        { label: "Duplicate enrolments", value: fmt(conf), sub: `${k.open_conflicts.EXACT ?? 0} same APAAR, ${k.open_conflicts.FUZZY ?? 0} probable`, tone: conf ? "bad" : "default" },
        { label: "Open anomalies", value: fmt(k.open_anomalies), tone: k.open_anomalies ? "warn" : "default", sub: "Rule and statistical" },
      ]} />

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <Panel title="States" actions={<Segmented value={metric} onChange={(v) => setMetric(v as any)}
          options={[{ id: "students", label: "Students" }, { id: "fill", label: "Fill rate" }, { id: "anomalies", label: "Anomalies" }]} />}>
          <div className="grid items-start gap-6 md:grid-cols-[1fr_250px]">
            <IndiaTiles rows={d.by_state} metric={metric} onPick={(s) => nav(`/aicte/institutions?state=${s}`)} />
            <table className="tbl text-[13px]">
              <thead><tr><th>State</th><th className="num">Students</th><th className="num">Fill</th></tr></thead>
              <tbody>{[...d.by_state].sort((a: any, b: any) => b.students - a.students).map((s: any) => (
                <tr key={s.state}>
                  <td className="whitespace-nowrap py-1.5"><Link className="link" to={`/aicte/institutions?state=${s.state}`}>{STATE_NAME[s.state] ?? s.state}</Link>
                    {s.anomalies > 0 && <span className="ml-1.5 text-xs font-medium text-red-700">{s.anomalies}</span>}</td>
                  <td className="num py-1.5">{fmt(s.students)}</td><td className="num py-1.5">{pct(s.fill)}</td></tr>))}</tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Activity" flush actions={<Link className="link text-[13px]" to="/aicte/audit">Audit log</Link>}>
          <ul className="max-h-[460px] divide-y divide-ink-100 overflow-y-auto">
            {events.length === 0 && <li className="px-4 py-6 text-sm text-ink-500">No activity yet.</li>}
            {events.map((e) => (
              <li key={e.id} className={`px-4 py-2.5 ${feed.includes(e) ? "bg-brand-50/50" : ""}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium text-ink-900">{EVENT_LABEL[e.type] ?? e.type}</span>
                  <span className="shrink-0 text-xs text-ink-500 tabular">{when(e.at)}</span>
                </div>
                <div className="text-[13px] text-ink-600">{describe(e)}</div>
              </li>))}
          </ul>
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Admissions by year" description="2021–2025 from annual returns; 2026 from student-level records">
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={d.trend} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="#eceef1" vertical={false} />
              <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: "#dcdfe4" }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={[0, yMax]} ticks={yTicks}
                tickFormatter={(v) => (v === 0 ? "0" : `${v / 1000}k`)} />
              <Tooltip formatter={(v: number) => fmt(v)} contentStyle={{ fontSize: 12, borderRadius: 4, borderColor: "#dcdfe4" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} iconType="plainline" />
              <Line dataKey="approved" stroke="#9fb9dc" strokeWidth={2} strokeDasharray="4 3" dot={false} name="Approved intake" />
              <Line dataKey="admitted" stroke="#0f3e7a" strokeWidth={2} dot={{ r: 2.5 }} name="Admitted" />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="By discipline" flush>
          <table className="tbl text-[13px]">
            <thead><tr><th>Discipline</th><th className="num">Approved</th><th className="num">Admitted</th><th className="num">Fill</th></tr></thead>
            <tbody>{d.by_discipline.map((r: any) => (
              <tr key={r.discipline}><td>{r.discipline}</td><td className="num">{fmt(r.approved)}</td><td className="num">{fmt(r.regular)}</td><td className="num">{pct(r.fill)}</td></tr>))}</tbody>
          </table>
        </Panel>
        <Panel title="Social category">
          <ul className="space-y-3">
            {Object.entries(d.categories as Record<string, number>).map(([c, v]) => (
              <li key={c} className="text-[13px]">
                <div className="mb-1 flex justify-between"><span>{CAT_LABEL[c] ?? c}</span><span className="tabular text-ink-600">{fmt(v)} · {pct(v / catTotal, 1)}</span></div>
                <div className="h-2 bg-ink-100"><div className="h-2 bg-brand-600" style={{ width: `${(v / catTotal) * 100}%` }} /></div>
              </li>))}
          </ul>
        </Panel>
      </div>

      <Panel title="Open anomalies" flush actions={<Link className="btn-secondary btn-sm" to="/aicte/anomalies">View all</Link>}>
        <table className="tbl tbl-hover">
          <thead><tr><th>Institution</th><th>Finding</th><th>Type</th><th>Severity</th></tr></thead>
          <tbody>{(anomalies.data ?? []).map((a: any) => (
            <tr key={a.id} onClick={() => nav(`/aicte/anomalies?focus=${a.id}`)}>
              <td><div className="font-medium">{a.institution}</div><div className="text-xs text-ink-500">{a.institution_code} · {STATE_NAME[a.state] ?? a.state}</div></td>
              <td className="text-ink-800">{a.title}</td>
              <td><Status s={a.source} /></td>
              <td><Status s={a.severity} /></td>
            </tr>))}</tbody>
        </table>
      </Panel>
    </div>
  );
}

function describe(e: SpineEvent): string {
  const p = e.payload || {};
  switch (e.type) {
    case "CONFLICT_OPENED": return `${p.kind === "FUZZY" ? `Probable match (${Math.round((p.score ?? 0) * 100)}%)` : "Same APAAR ID"} reported by two institutions. Case #${p.conflict_id}.`;
    case "ANOMALY_RAISED": return `${p.institution}: ${p.title}`;
    case "INTAKE_ALERT": return p.title;
    case "SUBMISSION_PROCESSED": return `${p.source === "FIX" ? "Correction" : p.source} · ${p.total} rows · ${p.created} accepted, ${p.rejected} returned, ${p.conflict} duplicate${p.conflict === 1 ? "" : "s"}`;
    case "CONFLICT_RESOLVED": return p.resolution ?? "";
    case "CONFLICT_STUDENT_CONFIRMED": return `Student responded to case #${p.conflict_id}.`;
    default: return e.actor;
  }
}
