import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useLiveEvents } from "../../lib/live";
import { Alert, day, Empty, ErrorText, Loading, Modal, PageHeader, Panel, Segmented, Status, Tabs, useAsync, useToast, when } from "../../components/ui";

export default function Conflicts() {
  const { user } = useAuth();
  const isAicte = user?.role === "AICTE_ADMIN";
  const [tab, setTab] = useState("open");
  const [kind, setKind] = useState("");
  const list = useAsync(() => api.get(`/api/v1/conflicts?status=${tab === "open" ? "open" : tab}${kind ? `&kind=${kind}` : ""}`), [tab, kind]);
  const [sel, setSel] = useState<any>(null);
  const { toast, node } = useToast();
  useLiveEvents((e) => { if (e.type.startsWith("CONFLICT")) list.reload(); });

  return (
    <div>
      {node}
      <PageHeader title="Duplicate enrolments"
        description={isAicte ? "Students reported as actively enrolled by more than one institution. Each case is decided on the student's response and the evidence, not on which report arrived first."
          : "Students you reported who also appear at another institution. The other institution is not identified to you."} />
      <Tabs active={tab} onChange={setTab} tabs={[{ id: "open", label: "Open" }, { id: "RESOLVED", label: "Resolved" }, { id: "DISMISSED", label: "Dismissed" }]} />
      <div className="mb-4">
        <Segmented value={kind} onChange={setKind} options={[{ id: "", label: "All" }, { id: "EXACT", label: "Same APAAR" }, { id: "FUZZY", label: "Probable match" }]} />
      </div>
      <Panel flush>
        {list.loading ? <Loading /> : list.error ? <div className="p-4"><ErrorText error={list.error} /></div> : !list.data?.length ? <Empty>No cases.</Empty> : (
          <div className="overflow-x-auto"><table className="tbl tbl-hover">
            <thead><tr><th className="num">Case</th><th>Student</th><th>Match</th><th>First reported by</th><th>Also reported by</th><th>Status</th></tr></thead>
            <tbody>{list.data.map((c: any) => (
              <tr key={c.id} onClick={() => setSel(c)}>
                <td className="num text-ink-500">#{c.id}</td>
                <td><div className="font-medium">{c.a.student_name ?? c.b.student_name ?? "—"}</div><div className="mono text-xs text-ink-500">{c.a.apaar ?? c.b.apaar ?? c.b.provisional_id}</div></td>
                <td><Status s={c.kind} />{c.kind === "FUZZY" && <div className="mt-0.5 text-xs text-ink-500">{Math.round(c.score * 100)}% similarity</div>}</td>
                <td><Side s={c.a} /></td><td><Side s={c.b} /></td>
                <td><Status s={c.status} /></td>
              </tr>))}</tbody>
          </table></div>)}
      </Panel>
      <Modal open={!!sel} onClose={() => setSel(null)} title={`Case #${sel?.id}`} wide>
        {sel && <Detail c={sel} isAicte={isAicte} canEvidence={user?.role === "INSTITUTION_ADMIN"}
          onDone={(msg) => { toast(msg); setSel(null); list.reload(); }} />}
      </Modal>
    </div>
  );
}

function Side({ s }: { s: any }) {
  return <div className="min-w-[200px]"><div className={s.institution_id ? "text-ink-900" : "italic text-ink-500"}>{s.institution}{s.yours && <span className="ml-1.5 text-xs text-ink-500">(you)</span>}</div>
    {s.program && <div className="text-xs text-ink-500">{s.program}</div>}
    <div className="text-xs text-ink-500">Reported {when(s.reported_at)}</div></div>;
}

function Detail({ c, isAicte, canEvidence, onDone }: { c: any; isAicte: boolean; canEvidence: boolean; onDone: (m: string) => void }) {
  const [note, setNote] = useState("");
  const [winner, setWinner] = useState<number | null>(c.student_choice_enrollment_id ?? null);
  const [action, setAction] = useState("VOID");
  const [err, setErr] = useState<string | null>(null);
  const open = ["OPEN", "STUDENT_CONFIRMED"].includes(c.status);
  async function resolve(decision?: string) {
    setErr(null);
    try { await api.post(`/api/v1/conflicts/${c.id}/resolve`, { winner_enrollment_id: winner, loser_action: action, decision, note }); onDone("Case resolved"); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="space-y-5">
      <div className="text-[13px] text-ink-600">Basis: {(c.reasons ?? []).join("; ")}.</div>
      <div className="grid gap-3 md:grid-cols-2">
        {[c.a, c.b].map((s: any, i: number) => {
          const selected = winner === s.enrollment_id;
          return (
            <label key={s.enrollment_id} className={`block rounded border p-4 ${selected ? "border-brand-600 bg-brand-50/50 ring-1 ring-brand-600" : "border-ink-200"} ${isAicte && open ? "cursor-pointer" : ""}`}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">{i === 0 ? "First reported" : "Also reported"}</span>
                {isAicte && open && <input type="radio" name="winner" checked={selected} onChange={() => setWinner(s.enrollment_id)} />}
              </div>
              <div className="mt-1.5 font-medium">{s.institution}</div>
              {s.program && <div className="text-[13px] text-ink-600">{s.program}</div>}
              <div className="mt-2 space-y-0.5 text-[13px] text-ink-600">
                {s.student_name && <div>{s.student_name} <span className="mono text-ink-500">{s.apaar ?? s.provisional_id}</span></div>}
                {s.roll_no && <div>Roll <span className="mono">{s.roll_no}</span> · {s.seat_type?.toLowerCase()} seat</div>}
                {s.admission_date && <div>Admitted {day(s.admission_date)}</div>}
                <div>Reported {when(s.reported_at)}</div>
              </div>
              {c.student_choice_enrollment_id === s.enrollment_id && <div className="mt-2 text-[13px] font-medium text-brand-700">Student confirms studying here</div>}
            </label>);
        })}
      </div>
      {c.student_note && <Alert title="Student's note">{c.student_note}</Alert>}
      {(c.evidence ?? []).length > 0 && (
        <div><h3 className="mb-1 text-[13px] font-semibold text-ink-700">Evidence</h3>
          <ul className="space-y-1 text-[13px]">{c.evidence.map((e: any, i: number) => <li key={i}>{e.note} <span className="text-ink-500">— {e.by}, {when(e.at)}</span></li>)}</ul></div>)}
      {c.resolution && <Alert tone="success" title="Decision">{c.resolution} ({c.resolved_by})</Alert>}
      {open && canEvidence && (
        <div><label className="label" htmlFor="ev">Add evidence</label>
          <div className="flex gap-2"><input id="ev" className="input" placeholder="Fee receipt number, attendance record, admission letter" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn-primary" disabled={!note} onClick={async () => { await api.post(`/api/v1/conflicts/${c.id}/evidence`, { note }); onDone("Evidence added"); }}>Add</button></div></div>)}
      {open && isAicte && (
        <div className="space-y-3 border-t border-ink-200 pt-4">
          <h3 className="text-sm font-semibold">Decision</h3>
          <div><label className="label" htmlFor="act">The other enrolment will be</label>
            <select id="act" className="input w-auto" value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="VOID">Voided (never valid)</option><option value="TRANSFER">Closed as transferred out</option></select></div>
          <div><label className="label" htmlFor="dn">Note</label><input id="dn" className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Recorded in the audit log" /></div>
          <ErrorText error={err} />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={!winner} onClick={() => resolve(c.kind === "FUZZY" ? "SAME_PERSON" : undefined)}>
              {c.kind === "FUZZY" ? "Same student: keep selected enrolment" : "Confirm selected enrolment"}</button>
            {c.kind === "FUZZY" && <button className="btn-secondary" onClick={() => resolve("DIFFERENT_PERSONS")}>Different students</button>}
          </div>
        </div>)}
    </div>
  );
}
