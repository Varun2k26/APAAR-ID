import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { DL, Empty, ErrorText, Modal, PageHeader, Panel, Status, Tabs, useAsync, useToast, when, Alert } from "../../components/ui";

const FIELDS: [string, string][] = [["name", "Name"], ["dob", "Date of birth"], ["gender", "Gender"], ["parent_name", "Parent or guardian"],
  ["apaar_id", "APAAR ID"], ["institution", "Institution"], ["program", "Programme"], ["admission_year", "Admission year"],
  ["year_of_study", "Year of study"], ["enrollment_status", "Enrolment status"], ["seat_type", "Seat type"],
  ["social_category", "Social category"], ["nationality", "Nationality"]];
const FIELD_LABEL = Object.fromEntries(FIELDS);

export default function Requests() {
  const { user } = useAuth();
  const iid = user!.institution!.id;
  const [tab, setTab] = useState("access");
  const consents = useAsync(() => api.get("/api/v1/consents"), []);
  const transfers = useAsync(() => api.get("/api/v1/transfers"), []);
  const corrections = useAsync(() => api.get("/api/v1/corrections"), []);
  const programs = useAsync(() => api.get(`/api/v1/institutions/${iid}/programs/list`), []);
  const { toast, node } = useToast();
  const [form, setForm] = useState({ apaar_id: "", purpose: "", fields: ["name", "program", "institution", "enrollment_status"], duration_days: 30 });
  const [tf, setTf] = useState({ apaar_id: "", to_program_id: "", to_roll_no: "", reason: "" });
  const [err, setErr] = useState<string | null>(null);
  const [record, setRecord] = useState<any>(null);
  const openCorr = (corrections.data ?? []).filter((c: any) => c.status === "OPEN").length;

  async function requestConsent() {
    setErr(null);
    try { await api.post("/api/v1/consents", form); toast("Request sent to the student"); consents.reload(); } catch (e: any) { setErr(e.message); }
  }
  async function view(apaar: string) {
    try { setRecord(await api.get(`/api/v1/records/${apaar.replace(/\s/g, "")}`)); } catch (e: any) { toast(e.message, "bad"); }
  }
  async function requestTransfer() {
    setErr(null);
    try { await api.post("/api/v1/transfers", { ...tf, to_program_id: Number(tf.to_program_id) }); toast("Transfer requested. Awaiting the student's consent."); transfers.reload(); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <div>
      {node}
      <PageHeader title="Requests" description="Access to records of students not enrolled with you, incoming and outgoing transfers, and corrections requested by your students." />
      <Tabs active={tab} onChange={(t) => { setTab(t); setErr(null); }} tabs={[{ id: "access", label: "Record access" }, { id: "transfer", label: "Transfers" }, { id: "corr", label: "Corrections", count: openCorr }]} />
      {tab === "access" && (
        <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <Panel title="Request access">
            <div className="space-y-4">
              <div><label className="label" htmlFor="ca">Student's APAAR ID</label><input id="ca" className="input mono" value={form.apaar_id} onChange={(e) => setForm({ ...form, apaar_id: e.target.value })} /></div>
              <div><label className="label" htmlFor="cp">Purpose</label><input id="cp" className="input" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} placeholder="Lateral entry admission verification" />
                <p className="help">Shown to the student.</p></div>
              <fieldset><legend className="label">Information requested</legend>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">{FIELDS.map(([f, l]) => (
                  <label key={f} className="flex items-center gap-2 text-[13px] text-ink-700">
                    <input type="checkbox" checked={form.fields.includes(f)} onChange={() => setForm({ ...form, fields: form.fields.includes(f) ? form.fields.filter((x) => x !== f) : [...form.fields, f] })} />{l}</label>))}</div></fieldset>
              <div><label className="label" htmlFor="cd">Access period (days)</label><input id="cd" className="input w-24" type="number" min={1} max={365} value={form.duration_days} onChange={(e) => setForm({ ...form, duration_days: Number(e.target.value) })} /></div>
              <ErrorText error={err} /><button className="btn-primary" onClick={requestConsent} disabled={!form.apaar_id || form.purpose.length < 8 || !form.fields.length}>Send request</button>
            </div>
          </Panel>
          <Panel title="Your requests" flush>
            {!consents.data?.length ? <Empty>No requests.</Empty> : (
              <table className="tbl"><thead><tr><th>Student</th><th>Purpose</th><th>Status</th><th /></tr></thead>
                <tbody>{consents.data.map((c: any) => (
                  <tr key={c.id}><td><div className="mono">{c.apaar}</div>{c.student && <div className="text-[13px] text-ink-600">{c.student}</div>}</td>
                    <td className="text-[13px]"><div>{c.purpose}</div><div className="text-ink-500">{c.fields.map((f: string) => FIELD_LABEL[f] ?? f).join(", ")}</div></td>
                    <td><Status s={c.expired ? "EXPIRED" : c.status} />{c.expires_at && !c.expired && c.status === "APPROVED" && <div className="mt-0.5 text-xs text-ink-500">Until {when(c.expires_at)}</div>}</td>
                    <td className="text-right">{c.status === "APPROVED" && !c.expired && <button className="btn-secondary btn-sm" onClick={() => view(c.apaar)}>View record</button>}</td></tr>))}</tbody></table>)}
          </Panel>
        </div>)}
      {tab === "transfer" && (
        <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <Panel title="Request a transfer in" description="The student is asked for consent, then their current institution releases them.">
            <div className="space-y-4">
              <div><label className="label" htmlFor="ta">Student's APAAR ID</label><input id="ta" className="input mono" value={tf.apaar_id} onChange={(e) => setTf({ ...tf, apaar_id: e.target.value })} /></div>
              <div><label className="label" htmlFor="tp">Programme</label><select id="tp" className="input" value={tf.to_program_id} onChange={(e) => setTf({ ...tf, to_program_id: e.target.value })}>
                <option value="">Select a programme</option>{(programs.data ?? []).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
              <div><label className="label" htmlFor="tr">New roll number</label><input id="tr" className="input mono" value={tf.to_roll_no} onChange={(e) => setTf({ ...tf, to_roll_no: e.target.value })} /></div>
              <div><label className="label" htmlFor="tx">Reason</label><input id="tx" className="input" value={tf.reason} onChange={(e) => setTf({ ...tf, reason: e.target.value })} /></div>
              <ErrorText error={err} /><button className="btn-primary" onClick={requestTransfer} disabled={!tf.apaar_id || !tf.to_program_id || !tf.to_roll_no}>Request transfer</button>
            </div>
          </Panel>
          <Panel title="Transfers" flush>
            {!transfers.data?.length ? <Empty>No transfers.</Empty> : (
              <table className="tbl"><thead><tr><th>Student</th><th>From</th><th>To</th><th>Status</th><th /></tr></thead>
                <tbody>{transfers.data.map((t: any) => {
                  const outgoing = t.from_institution_id === iid;
                  return (
                    <tr key={t.id}><td><div>{t.student}</div><div className="mono text-xs text-ink-500">{t.apaar}</div></td>
                      <td className="text-[13px]">{t.from_institution}</td><td className="text-[13px]">{t.to_institution}<div className="text-ink-500">{t.to_program}</div></td>
                      <td><Status s={t.status} /></td>
                      <td className="text-right">{outgoing && t.status === "PENDING_RELEASE" && <div className="flex justify-end gap-1">
                        <button className="btn-primary btn-sm" onClick={async () => { await api.post(`/api/v1/transfers/${t.id}/release`); toast("Student released"); transfers.reload(); }}>Release</button>
                        <button className="btn-secondary btn-sm" onClick={async () => { await api.post(`/api/v1/transfers/${t.id}/reject`); transfers.reload(); }}>Decline</button></div>}</td></tr>);
                })}</tbody></table>)}
          </Panel>
        </div>)}
      {tab === "corr" && (
        <Panel flush>
          {!corrections.data?.length ? <Empty>No correction requests.</Empty> : (
            <table className="tbl"><thead><tr><th>Student</th><th>Field</th><th>Current</th><th>Requested</th><th>Reason</th><th>Status</th><th /></tr></thead>
              <tbody>{corrections.data.map((c: any) => (
                <tr key={c.id}><td><div>{c.student}</div><div className="mono text-xs text-ink-500">{c.roll_no}</div></td>
                  <td>{FIELD_LABEL[c.field] ?? c.field}</td><td>{c.current_value}</td><td className="font-medium">{c.requested_value}</td>
                  <td className="text-[13px] text-ink-600">{c.reason ?? "—"}</td><td><Status s={c.status} /></td>
                  <td className="text-right">{c.status === "OPEN" && <div className="flex justify-end gap-1">
                    <button className="btn-primary btn-sm" onClick={async () => { try { await api.post(`/api/v1/corrections/${c.id}/decide`, { accept: true }); toast("Correction applied"); } catch (e: any) { toast(e.message, "bad"); } corrections.reload(); }}>Accept</button>
                    <button className="btn-secondary btn-sm" onClick={async () => { await api.post(`/api/v1/corrections/${c.id}/decide`, { accept: false }); corrections.reload(); }}>Decline</button></div>}</td></tr>))}</tbody></table>)}
        </Panel>)}
      <Modal open={!!record} onClose={() => setRecord(null)} title={record?.name ?? "Student record"}>
        {record && <div className="space-y-4">
          <Alert>Shared with the student's consent ({record._access_basis}). Only the approved information is shown.</Alert>
          <DL rows={Object.entries(record).filter(([k]) => !k.startsWith("_") && k !== "enrollments").map(([k, v]) => [FIELD_LABEL[k] ?? k, String(v)])} />
          {(record.enrollments ?? []).map((e: any, i: number) => (
            <div key={i}><h3 className="mb-1 text-[13px] font-semibold text-ink-700">Enrolment</h3>
              <DL rows={Object.entries(e).map(([k, v]) => [FIELD_LABEL[k] ?? k.replace(/_/g, " "), String(v)])} /></div>))}
        </div>}
      </Modal>
    </div>
  );
}
