import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { day, DL, Empty, ErrorText, Loading, Modal, PageHeader, Panel, Status, useAsync, useToast, when } from "../../components/ui";

const SEAT: Record<string, string> = { MERIT: "Merit", MANAGEMENT: "Management", NRI: "NRI", TFW: "Tuition fee waiver", FOREIGN: "FN / OCI / PIO", LATERAL: "Lateral entry" };
const FIELD: Record<string, string> = { name: "Name", dob: "Date of birth", gender: "Gender", parent_name: "Parent or guardian", apaar_id: "APAAR ID",
  institution: "Institution", program: "Programme", admission_year: "Admission year", year_of_study: "Year of study",
  enrollment_status: "Enrolment status", seat_type: "Seat type", social_category: "Social category", nationality: "Nationality" };
const CORRECTABLE: [string, string][] = [["social_category", "Social category"], ["seat_type", "Seat type"], ["nationality", "Nationality"], ["year_of_study", "Year of study"], ["parent_name", "Parent or guardian"]];

export default function StudentHome() {
  const me = useAsync(() => api.get("/api/v1/me/record"), []);
  const conflicts = useAsync(() => api.get("/api/v1/conflicts?status=open"), []);
  const consents = useAsync(() => api.get("/api/v1/consents"), []);
  const corrections = useAsync(() => api.get("/api/v1/corrections"), []);
  const { toast, node } = useToast();
  const [corr, setCorr] = useState<any>(null);
  if (me.loading) return <Loading />;
  if (me.error) return <ErrorText error={me.error} />;
  const r = me.data;
  const reload = () => { me.reload(); conflicts.reload(); consents.reload(); corrections.reload(); };
  const pending = (consents.data ?? []).filter((c: any) => c.status === "PENDING");
  return (
    <div className="space-y-6">
      {node}
      <PageHeader title="My record" meta={<><span>{r.name}</span><span className="mono">{r.apaar_id ?? r.provisional_id}</span></>} />

      {(conflicts.data ?? []).map((c: any) => (
        <section key={c.id} className="panel border-l-4 border-l-red-700">
          <div className="px-5 py-4">
            <h2 className="text-[15px] font-semibold">Two institutions have reported you as their student</h2>
            <p className="mt-1 text-sm text-ink-600">You can only be enrolled in one regular programme at a time. Tell us where you are studying. AICTE will review your answer with the institutions' records.</p>
            <div className="mt-4 grid gap-3 md:grid-cols-2">{[c.a, c.b].map((s: any) => {
              const chosen = c.student_choice_enrollment_id === s.enrollment_id;
              return (
                <div key={s.enrollment_id} className={`rounded border p-4 ${chosen ? "border-brand-600 ring-1 ring-brand-600" : "border-ink-200"}`}>
                  <div className="font-medium">{s.institution}</div>
                  <div className="text-[13px] text-ink-600">{s.program} · roll {s.roll_no}</div>
                  <div className="text-xs text-ink-500">Reported {when(s.reported_at)}</div>
                  {chosen ? <div className="mt-3 text-[13px] font-medium text-brand-700">You told us you study here</div>
                    : <button className="btn-secondary btn-sm mt-3" onClick={async () => { await api.post(`/api/v1/conflicts/${c.id}/student-confirm`, { enrollment_id: s.enrollment_id }); toast("Your answer has been sent to AICTE"); reload(); }}>I study here</button>}
                </div>);
            })}</div>
          </div>
        </section>))}

      {pending.length > 0 && (
        <Panel title="Requests to access your record" flush>
          <ul className="divide-y divide-ink-100">{pending.map((c: any) => (
            <li key={c.id} className="flex flex-wrap items-start justify-between gap-4 px-4 py-4">
              <div className="min-w-0">
                <div className="font-medium">{c.requester}</div>
                <div className="text-sm text-ink-700">{c.purpose}</div>
                <div className="mt-1 text-[13px] text-ink-500">Wants to see: {c.fields.map((f: string) => FIELD[f] ?? f).join(", ")}. Access for {c.duration_days} days.</div>
              </div>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={async () => { await api.post(`/api/v1/consents/${c.id}/decide`, { approve: false }); toast("Request declined"); reload(); }}>Decline</button>
                <button className="btn-primary" onClick={async () => { await api.post(`/api/v1/consents/${c.id}/decide`, { approve: true }); toast("Access granted"); reload(); }}>Allow</button>
              </div>
            </li>))}</ul>
        </Panel>)}

      <div className="grid gap-6 lg:grid-cols-[1fr_1.5fr]">
        <Panel title="Personal details">
          <DL rows={[["Name", r.name], ["APAAR ID", <span className="mono">{r.apaar_id ?? r.provisional_id}</span>], ["Verification", <Status s={r.registry_status} />],
            ["Date of birth", day(r.dob)], ["Parent or guardian", r.parent_name]]} />
          <p className="help mt-3">Name and date of birth come from your APAAR record. Corrections to these are made through APAAR.</p>
        </Panel>
        <Panel title="Enrolments" flush>
          {!r.enrollments.length ? <Empty>No enrolments.</Empty> : (
            <ul className="divide-y divide-ink-100">{r.enrollments.map((e: any) => (
              <li key={e.enrollment_id} className="px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><div className="font-medium">{e.institution}</div><div className="text-sm text-ink-600">{e.program}</div></div>
                  <Status s={e.enrollment_status} />
                </div>
                <div className="mt-2 text-[13px] text-ink-500">Roll <span className="mono">{e.roll_no}</span> · Admitted {day(e.admission_date)} · Year {e.year_of_study} · {SEAT[e.seat_type] ?? e.seat_type} · {e.social_category}</div>
                <div className="mt-3 flex gap-2">
                  {e.enrollment_status === "ACTIVE" && <Link to="/student/wallet" className="btn-secondary btn-sm">Get enrolment credential</Link>}
                  <button className="btn-quiet btn-sm" onClick={() => setCorr({ enrollment_id: e.enrollment_id, field: "social_category", requested_value: "", reason: "" })}>Request a correction</button>
                </div>
              </li>))}</ul>)}
        </Panel>
      </div>

      <Panel title="Access you have granted" flush>
        {!(consents.data ?? []).filter((c: any) => c.status !== "PENDING").length ? <Empty>You have not granted access to anyone.</Empty> : (
          <table className="tbl"><thead><tr><th>Organisation</th><th>Purpose</th><th>Status</th><th /></tr></thead>
            <tbody>{consents.data.filter((c: any) => c.status !== "PENDING").map((c: any) => (
              <tr key={c.id}><td>{c.requester}</td><td className="text-[13px]">{c.purpose}<div className="text-ink-500">{c.fields.map((f: string) => FIELD[f] ?? f).join(", ")}</div></td>
                <td><Status s={c.expired ? "EXPIRED" : c.status} />{c.status === "APPROVED" && !c.expired && <div className="mt-0.5 text-xs text-ink-500">Until {when(c.expires_at)}</div>}</td>
                <td className="text-right">{c.status === "APPROVED" && !c.expired && <button className="btn-secondary btn-sm" onClick={async () => { await api.post(`/api/v1/consents/${c.id}/revoke`); toast("Access withdrawn"); reload(); }}>Withdraw</button>}</td></tr>))}</tbody></table>)}
      </Panel>

      {(corrections.data ?? []).length > 0 && (
        <Panel title="Correction requests" flush>
          <table className="tbl"><thead><tr><th>Field</th><th>Current</th><th>Requested</th><th>Status</th></tr></thead>
            <tbody>{corrections.data.map((c: any) => <tr key={c.id}><td>{FIELD[c.field] ?? c.field}</td><td>{c.current_value}</td><td>{c.requested_value}</td><td><Status s={c.status} /></td></tr>)}</tbody></table>
        </Panel>)}

      <Modal open={!!corr} onClose={() => setCorr(null)} title="Request a correction"
        footer={<><button className="btn-secondary" onClick={() => setCorr(null)}>Cancel</button>
          <button className="btn-primary" disabled={!corr?.requested_value} onClick={async () => { try { await api.post("/api/v1/me/corrections", corr); toast("Sent to your institution"); setCorr(null); reload(); } catch (e: any) { toast(e.message, "bad"); } }}>Send to institution</button></>}>
        {corr && <div className="space-y-4">
          <div><label className="label" htmlFor="cf">Field</label><select id="cf" className="input" value={corr.field} onChange={(e) => setCorr({ ...corr, field: e.target.value })}>
            {CORRECTABLE.map(([f, l]) => <option key={f} value={f}>{l}</option>)}</select></div>
          <div><label className="label" htmlFor="cv">Correct value</label><input id="cv" className="input" value={corr.requested_value} onChange={(e) => setCorr({ ...corr, requested_value: e.target.value })} /></div>
          <div><label className="label" htmlFor="cr">Reason</label><input id="cr" className="input" value={corr.reason} onChange={(e) => setCorr({ ...corr, reason: e.target.value })} /></div>
        </div>}
      </Modal>
    </div>
  );
}
