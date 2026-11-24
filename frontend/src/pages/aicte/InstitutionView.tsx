import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { day, DL, ErrorText, Findings, fmt, Loading, Modal, PageHeader, Pager, Panel, pct, Stats, Status, useAsync, when } from "../../components/ui";
import ProgramTable from "../../components/ProgramTable";
import { STATE_NAME } from "../../components/IndiaTiles";
import { EVENT_LABEL } from "../../lib/live";

const TYPE: Record<string, string> = { PRIVATE: "Private", GOVT: "Government", AIDED: "Aided" };

export default function InstitutionView() {
  const { id } = useParams();
  const d = useAsync(() => api.get(`/api/v1/analytics/institutions/${id}`), [id]);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const list = useAsync(() => api.get(`/api/v1/enrollments?institution_id=${id}&page=${page}&size=25${q ? `&q=${encodeURIComponent(q)}` : ""}`), [id, page, q]);
  const [open, setOpen] = useState<number | null>(null);
  if (d.loading) return <Loading />;
  if (d.error) return <ErrorText error={d.error} />;
  const { institution: i, kpis: k, programs, anomalies } = d.data;
  return (
    <div className="space-y-6">
      <PageHeader title={i.name} crumbs={[{ label: "Institutions", to: "/aicte/institutions" }, { label: i.code }]}
        meta={<><span>{i.code}</span><span>{i.district}, {STATE_NAME[i.state] ?? i.state}</span><span>{TYPE[i.type] ?? i.type}</span></>} />
      <Stats items={[
        { label: "Students", value: fmt(k.students), sub: `${fmt(k.supernumerary)} supernumerary` },
        { label: "Fill rate", value: pct(k.fill), sub: `${fmt(k.regular)} of ${fmt(k.approved)} approved`, tone: k.fill > 1 ? "bad" : "default" },
        { label: "APAAR coverage", value: pct(k.apaar_coverage, 1), sub: `${k.provisional} provisional`, tone: k.apaar_coverage < 0.85 ? "bad" : "default" },
        { label: "Returned rows", value: fmt(k.open_errors), sub: `${fmt(k.open_warnings)} warnings` },
        { label: "Anomalies", value: anomalies.length, tone: anomalies.length ? "warn" : "default" },
      ]} />
      {anomalies.length > 0 && (
        <Panel title="Anomalies" flush>
          <table className="tbl"><tbody>{anomalies.map((a: any) => (
            <tr key={a.id}><td className="w-28"><Status s={a.source} /></td>
              <td><div className="font-medium">{a.title}</div>{a.explanation?.summary && <div className="text-[13px] text-ink-500">{a.explanation.summary}</div>}</td>
              <td className="w-24"><Status s={a.severity} /></td></tr>))}</tbody></table>
        </Panel>)}
      <Panel title="Programmes" description="Admissions against approved intake for the current academic year" flush><ProgramTable programs={programs} /></Panel>
      <Panel title="Students" flush description="Opening an individual record requires a reason, which is logged and visible to the student."
        actions={<input className="input w-64" placeholder="Name, roll number or APAAR" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Search students" />}>
        {list.loading ? <Loading /> : <EnrollmentTable rows={list.data?.items ?? []} onOpen={setOpen} />}
        <Pager page={page} total={list.data?.total ?? 0} size={25} onPage={setPage} />
      </Panel>
      <RecordModal id={open} onClose={() => setOpen(null)} needPurpose />
    </div>
  );
}

const SEAT: Record<string, string> = { MERIT: "Merit", MANAGEMENT: "Management", NRI: "NRI", TFW: "TFW", FOREIGN: "FN/OCI/PIO", LATERAL: "Lateral" };

export function EnrollmentTable({ rows, onOpen, actions }: { rows: any[]; onOpen: (id: number) => void; actions?: (r: any) => React.ReactNode }) {
  return (
    <div className="overflow-x-auto"><table className="tbl">
      <thead><tr><th>Roll no.</th><th>Name</th><th>APAAR / ID</th><th>Programme</th><th>Seat</th><th>Category</th><th>Status</th>{actions && <th className="text-right">Actions</th>}</tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.id}>
          <td className="mono">{r.roll_no}</td>
          <td><button className="link font-medium" onClick={() => onOpen(r.id)}>{r.name}</button></td>
          <td>{r.apaar ? <span className="mono">{r.apaar}</span> : <span className="mono text-amber-800">{r.provisional_id}</span>}
            {r.registry_status !== "VERIFIED" && <div className="mt-0.5"><Status s={r.registry_status} /></div>}</td>
          <td>{r.program}</td><td>{SEAT[r.seat_type] ?? r.seat_type}{r.year_of_study > 1 ? ` (year ${r.year_of_study})` : ""}</td>
          <td>{r.social_category}</td><td><Status s={r.status} /></td>
          {actions && <td className="text-right">{actions(r)}</td>}
        </tr>))}</tbody>
    </table></div>
  );
}

export function RecordModal({ id, onClose, needPurpose }: { id: number | null; onClose: () => void; needPurpose?: boolean }) {
  const [purpose, setPurpose] = useState("");
  const [rec, setRec] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = async (p?: string) => {
    setErr(null);
    try { setRec(await api.get(`/api/v1/enrollments/${id}${p ? `?purpose=${encodeURIComponent(p)}` : ""}`)); } catch (e: any) { setErr(e.message); }
  };
  useEffect(() => { if (id != null && !needPurpose) load(); /* eslint-disable-next-line */ }, [id]);
  const close = () => { setRec(null); setPurpose(""); setErr(null); onClose(); };
  return (
    <Modal open={id != null} onClose={close} title={rec ? rec.name : "Student record"} wide>
      {!rec && needPurpose && (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); load(purpose); }}>
          <div><label className="label" htmlFor="purpose">Reason for access</label>
            <input id="purpose" className="input" placeholder="For example: review of anomaly #12" value={purpose} onChange={(e) => setPurpose(e.target.value)} autoFocus />
            <p className="help">Recorded in the audit log and shown in the student's access history.</p></div>
          <ErrorText error={err} /><button className="btn-primary" disabled={purpose.trim().length < 5}>Open record</button>
        </form>)}
      {err && !needPurpose && <ErrorText error={err} />}
      {rec && (
        <div className="grid gap-6 md:grid-cols-[1.1fr_1fr]">
          <div>
            <DL rows={[
              ["APAAR ID", rec.apaar ? <span className="mono">{rec.apaar}</span> : <span className="mono">{rec.provisional_id} (provisional)</span>],
              ["Identity check", <Status s={rec.registry_status} />], ["Date of birth", day(rec.dob)], ["Gender", rec.gender],
              ["Parent or guardian", rec.parent_name], ["Qualifying exam roll", rec.exam_roll ? <span className="mono">{rec.exam_roll}</span> : null],
              ["Programme", rec.program_name], ["Roll number", <span className="mono">{rec.roll_no}</span>], ["Seat", SEAT[rec.seat_type] ?? rec.seat_type],
              ["Category", rec.social_category], ["Nationality", rec.nationality], ["Status", <Status s={rec.status} />],
            ]} />
            {rec.issues?.length > 0 && <div className="mt-4"><h3 className="mb-2 text-[13px] font-semibold text-ink-700">Validation findings</h3>
              <Findings findings={rec.issues.map((i: any) => ({ code: i.code, severity: i.severity, message: i.message }))} /></div>}
          </div>
          <div>
            <h3 className="mb-2 text-[13px] font-semibold text-ink-700">History</h3>
            <ol className="space-y-3 border-l border-ink-200 pl-4">{rec.history.map((h: any, n: number) => (
              <li key={n} className="relative text-[13px]">
                <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-ink-300" />
                <div className="font-medium text-ink-900">{EVENT_LABEL[h.type] ?? h.type}</div>
                <div className="text-xs text-ink-500">{when(h.at)} · {h.by}</div>
                {h.details?.changes && <div className="text-ink-600">{Object.entries(h.details.changes).map(([k, v]: any) => `${k.replace(/_/g, " ")}: ${v[0]} to ${v[1]}`).join("; ")}</div>}
                {h.details?.from && <div className="text-ink-600">{h.details.from.toLowerCase()} to {h.details.to.toLowerCase()}{h.details.reason ? ` (${h.details.reason})` : ""}</div>}
              </li>))}</ol>
          </div>
        </div>)}
    </Modal>
  );
}
