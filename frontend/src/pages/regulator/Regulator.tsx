import { useState } from "react";
import { api } from "../../lib/api";
import { Alert, day, Empty, ErrorText, fmt, Loading, PageHeader, Panel, Status, useAsync, when } from "../../components/ui";
import ProgramTable from "../../components/ProgramTable";

export default function Regulator() {
  const insts = useAsync(() => api.get("/api/v1/analytics/institutions?sort=name"), []);
  const history = useAsync(() => api.get("/api/v1/regulator/audit-queries"), []);
  const [iid, setIid] = useState("");
  const [purpose, setPurpose] = useState("");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function run() {
    setBusy(true); setErr(null);
    try { setRes(await api.post("/api/v1/regulator/audit-queries", { institution_id: Number(iid), purpose })); history.reload(); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <div className="space-y-6">
      <PageHeader title="Audit queries" description="Read-only access to an institution's enrolment records for accreditation and audit. Records are provided without names, dates of birth or APAAR IDs." />
      <Panel>
        <div className="grid gap-4 md:grid-cols-[1.2fr_2fr_auto] md:items-end">
          <div><label className="label" htmlFor="ri">Institution</label><select id="ri" className="input" value={iid} onChange={(e) => setIid(e.target.value)}>
            <option value="">Select an institution</option>{(insts.data ?? []).map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></div>
          <div><label className="label" htmlFor="rp">Purpose</label><input id="rp" className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="NAAC accreditation cycle 2026: enrolment verification" /></div>
          <button className="btn-primary" disabled={!iid || purpose.length < 10 || busy} onClick={run}>Run query</button>
        </div>
        <p className="help mt-2">The purpose is recorded and shown to every student included in the result.</p>
        {err && <div className="mt-3"><ErrorText error={err} /></div>}
      </Panel>
      {busy && <Loading />}
      {res && (<>
        <Alert title={`Query #${res.query_id}: ${res.institution.name}`}>{res.purpose}</Alert>
        <Panel title="Programmes" flush><ProgramTable programs={res.programs} /></Panel>
        <Panel title="Records" description={`${fmt(res.records.length)} enrolments`} flush>
          <div className="max-h-[440px] overflow-auto"><table className="tbl text-[13px]">
            <thead><tr><th>Reference</th><th>Programme</th><th>Seat</th><th>Category</th><th>Nationality</th><th>Identity</th><th>Status</th><th>Admitted</th></tr></thead>
            <tbody>{res.records.map((r: any, i: number) => (
              <tr key={i}><td className="mono">{r.ref}</td><td>{r.program}</td><td>{r.seat_type.toLowerCase()}</td><td>{r.social_category}</td><td>{r.nationality.replace("_", " ").toLowerCase()}</td>
                <td><Status s={r.identity} /></td><td><Status s={r.status} /></td><td className="whitespace-nowrap">{day(r.admission_date)}</td></tr>))}</tbody>
          </table></div>
        </Panel></>)}
      <Panel title="Previous queries" flush>
        {!history.data?.length ? <Empty>No queries yet.</Empty> : (
          <table className="tbl text-[13px]"><thead><tr><th className="num">Query</th><th>Date</th><th>Institution</th><th>Purpose</th><th className="num">Records</th></tr></thead>
            <tbody>{history.data.map((h: any) => (
              <tr key={h.id}><td className="num">#{h.id}</td><td className="whitespace-nowrap">{when(h.at)}</td><td>{(insts.data ?? []).find((i: any) => `institution:${i.id}` === h.resource)?.name ?? h.resource}</td>
                <td>{h.purpose}</td><td className="num">{fmt(h.details?.rows)}</td></tr>))}</tbody></table>)}
      </Panel>
    </div>
  );
}
