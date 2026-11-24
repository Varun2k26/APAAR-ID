import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { EVENT_LABEL, useLiveEvents } from "../../lib/live";
import { Alert, Empty, ErrorText, fmt, Loading, PageHeader, Panel, pct, Stats, useAsync, when } from "../../components/ui";
import ProgramTable from "../../components/ProgramTable";
import { STATE_NAME } from "../../components/IndiaTiles";

const CAT_LABEL: Record<string, string> = { GEN: "General", EWS: "EWS", "OBC-NCL": "OBC (NCL)", SC: "SC", ST: "ST" };
const SRC: Record<string, string> = { CSV: "File upload", API: "ERP (API)", FORM: "Web form", FIX: "Correction", SEED: "Migration" };

export default function InstDashboard() {
  const { user } = useAuth();
  const inst = user!.institution!;
  const d = useAsync(() => api.get(`/api/v1/analytics/institutions/${inst.id}`), [inst.id]);
  const subs = useAsync(() => api.get("/api/v1/submissions?limit=8"), []);
  const ev = useAsync(() => api.get("/api/v1/events/recent?limit=10&types=CONFLICT_OPENED,INTAKE_ALERT,CONSENT_DECIDED,TRANSFER_REQUESTED,CORRECTION_REQUESTED,CONFLICT_RESOLVED"), []);
  useLiveEvents((e) => { if (["SUBMISSION_PROCESSED", "CONFLICT_OPENED", "INTAKE_ALERT", "CONFLICT_RESOLVED", "TRANSFER_COMPLETED"].includes(e.type)) { d.reload(); subs.reload(); ev.reload(); } });
  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorText error={d.error} />;
  const { kpis: k, programs, anomalies, categories, institution: i } = d.data;
  const catTotal = Object.values(categories as Record<string, number>).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="space-y-6">
      <PageHeader title="Overview" meta={<><span>{i.name}</span><span>{i.code}</span><span>{i.district}, {STATE_NAME[i.state] ?? i.state}</span></>}
        actions={<><Link to="/institution/upload" className="btn-primary">Upload file</Link><Link to="/institution/add" className="btn-secondary">Add student</Link></>} />
      {anomalies.map((a: any) => <Alert key={a.id} tone="warn" title={a.title}>{a.explanation?.note}</Alert>)}
      <Stats items={[
        { label: "Students reported", value: fmt(k.students), sub: `${fmt(k.supernumerary)} supernumerary` },
        { label: "Fill rate", value: pct(k.fill), sub: `${fmt(k.regular)} of ${fmt(k.approved)} approved seats`, tone: k.fill > 1 ? "bad" : "default" },
        { label: "APAAR coverage", value: pct(k.apaar_coverage, 1), sub: `${k.provisional} awaiting APAAR`, tone: k.provisional ? "warn" : "default" },
        { label: "Rows to correct", value: fmt(k.open_errors), sub: `${fmt(k.open_warnings)} warnings to review`, tone: k.open_errors ? "bad" : "default" },
        { label: "Intake alerts", value: anomalies.length, tone: anomalies.length ? "bad" : "default" },
      ]} />
      <Panel title="Programmes" description="Admissions against approved intake. Supernumerary seats are counted against their own caps." flush>
        <ProgramTable programs={programs} />
      </Panel>
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Social category">
          <ul className="space-y-3">{Object.entries(categories as Record<string, number>).map(([c, v]) => (
            <li key={c} className="text-[13px]"><div className="mb-1 flex justify-between"><span>{CAT_LABEL[c] ?? c}</span><span className="tabular text-ink-600">{fmt(v)} · {pct(v / catTotal, 1)}</span></div>
              <div className="h-2 bg-ink-100"><div className="h-2 bg-brand-600" style={{ width: `${(v / catTotal) * 100}%` }} /></div></li>))}</ul>
        </Panel>
        <Panel title="Recent submissions" flush>
          {!subs.data?.length ? <Empty>Nothing submitted yet.</Empty> : (
            <table className="tbl text-[13px]"><thead><tr><th>Submitted</th><th>Source</th><th className="num">Rows</th><th className="num">Returned</th></tr></thead>
              <tbody>{subs.data.map((s: any) => (
                <tr key={s.id}><td className="whitespace-nowrap">{when(s.created_at)}</td><td>{SRC[s.source] ?? s.source}</td><td className="num">{s.total}</td>
                  <td className={`num ${s.rejected ? "font-semibold text-red-700" : ""}`}>{s.rejected}</td></tr>))}</tbody></table>)}
        </Panel>
        <Panel title="Notifications" flush>
          {!ev.data?.length ? <Empty>No notifications.</Empty> : (
            <ul className="divide-y divide-ink-100">{ev.data.map((e: any) => (
              <li key={e.id} className="px-4 py-2.5 text-[13px]"><div className="flex justify-between gap-2"><span className="font-medium">{EVENT_LABEL[e.type] ?? e.type}</span><span className="shrink-0 text-ink-500">{when(e.at)}</span></div>
                {(e.payload?.title || e.payload?.purpose) && <div className="text-ink-600">{e.payload.title ?? e.payload.purpose}</div>}</li>))}</ul>)}
        </Panel>
      </div>
    </div>
  );
}
