import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ErrorText, Loading, Modal, PageHeader, Pager, Panel, useAsync, useToast } from "../../components/ui";
import { EnrollmentTable, RecordModal } from "../aicte/InstitutionView";

const ACTIONS: Record<string, [string, string][]> = {
  ACTIVE: [["GRADUATE", "Graduate"], ["SUSPEND", "Suspend"], ["DROP", "Withdraw"]],
  SUSPENDED: [["REINSTATE", "Reinstate"], ["DROP", "Withdraw"]],
  DROPPED: [["RE_ENROL", "Re-enrol"]],
};
const ACTION_TITLE: Record<string, string> = { GRADUATE: "Record graduation", SUSPEND: "Suspend student", DROP: "Record withdrawal", REINSTATE: "Reinstate student", RE_ENROL: "Re-enrol student" };

export default function Students() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [prov, setProv] = useState(false);
  const [page, setPage] = useState(1);
  const list = useAsync(() => api.get(`/api/v1/enrollments?page=${page}&size=50${q ? `&q=${encodeURIComponent(q)}` : ""}${status ? `&status=${status}` : ""}${prov ? "&provisional=true" : ""}`), [q, status, prov, page]);
  const [open, setOpen] = useState<number | null>(null);
  const [act, setAct] = useState<{ r: any; action: string } | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  const canWrite = user?.permissions.includes("enrollment:write");

  async function doAction() {
    setErr(null);
    try { await api.post(`/api/v1/enrollments/${act!.r.id}/events`, { action: act!.action, reason }); toast("Status updated"); setAct(null); setReason(""); list.reload(); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <div>
      {node}
      <PageHeader title="Students" description="Students reported by your institution for the current academic year." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input className="input max-w-xs" placeholder="Name, roll number or APAAR ID" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Search" />
        <select className="input w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
          <option value="">All statuses</option>{[["ACTIVE", "Active"], ["CONFLICT", "Duplicate"], ["SUSPENDED", "Suspended"], ["DROPPED", "Withdrawn"], ["GRADUATED", "Graduated"], ["TRANSFERRED_OUT", "Transferred out"], ["VOID", "Void"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label className="flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" checked={prov} onChange={(e) => { setProv(e.target.checked); setPage(1); }} />Awaiting APAAR only</label>
      </div>
      <Panel flush>
        {list.loading ? <Loading /> : list.error ? <div className="p-4"><ErrorText error={list.error} /></div> :
          <EnrollmentTable rows={list.data.items} onOpen={setOpen} actions={canWrite ? (r) => (
            <div className="flex justify-end gap-1">{(ACTIONS[r.status] ?? []).map(([a, l]) => <button key={a} className="btn-quiet btn-sm" onClick={() => setAct({ r, action: a })}>{l}</button>)}</div>) : undefined} />}
        <Pager page={page} total={list.data?.total ?? 0} size={50} onPage={setPage} />
      </Panel>
      <RecordModal id={open} onClose={() => setOpen(null)} />
      <Modal open={!!act} onClose={() => setAct(null)} title={act ? ACTION_TITLE[act.action] : ""}
        footer={<><button className="btn-secondary" onClick={() => setAct(null)}>Cancel</button><button className="btn-primary" onClick={doAction}>Confirm</button></>}>
        {act && <div className="space-y-3">
          <p className="text-sm text-ink-700">{act.r.name} · <span className="mono">{act.r.roll_no}</span></p>
          {["DROP", "SUSPEND"].includes(act.action) && <p className="text-[13px] text-ink-500">Any enrolment credential issued to this student will be revoked.</p>}
          <div><label className="label" htmlFor="reason">Reason</label><input id="reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          <ErrorText error={err} />
        </div>}
      </Modal>
    </div>
  );
}
