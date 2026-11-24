import { useState } from "react";
import { api, openBlob } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Empty, ErrorText, Loading, Modal, PageHeader, Panel, Status, useAsync, useToast } from "../../components/ui";

export default function University() {
  const { user } = useAuth();
  const grads = useAsync(() => api.get("/api/v1/university/graduates"), []);
  const [sel, setSel] = useState<any>(null);
  const [form, setForm] = useState({ class_awarded: "First Class", cgpa: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  async function issue() {
    setErr(null); setBusy(true);
    try {
      const c = await api.post("/api/v1/university/degrees", { enrollment_id: sel.enrollment_id, class_awarded: form.class_awarded, cgpa: form.cgpa ? Number(form.cgpa) : null });
      toast("Degree issued"); setSel(null); grads.reload(); openBlob(`/api/v1/credentials/${c.id}/certificate.pdf`);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  const issued = (grads.data ?? []).filter((g: any) => g.degree && !g.degree.revoked).length;
  return (
    <div className="space-y-6">
      {node}
      <PageHeader title="Degrees" meta={<><span>{user?.university?.name}</span>{grads.data && <span>{issued} of {grads.data.length} graduates issued</span>}</>}
        description="Graduates reported by affiliated institutions. Each degree is signed by the university and carries the student's APAAR ID." />
      <Panel flush>
        {grads.loading ? <Loading /> : !grads.data?.length ? <Empty>No graduates reported.</Empty> : (
          <div className="overflow-x-auto"><table className="tbl">
            <thead><tr><th>Graduate</th><th>Institution</th><th>Programme</th><th>Batch</th><th>Degree</th><th /></tr></thead>
            <tbody>{grads.data.map((g: any) => (
              <tr key={g.enrollment_id}>
                <td><div className="font-medium">{g.name}</div><div className="mono text-xs text-ink-500">{g.apaar}</div></td>
                <td className="text-[13px]">{g.institution}</td><td className="text-[13px]">{g.program}<div className="mono text-ink-500">{g.roll_no}</div></td>
                <td>{g.admission_year}</td>
                <td>{g.degree ? <Status s={g.degree.revoked ? "REVOKED" : "ACTIVE"} label={g.degree.revoked ? "Revoked" : "Issued"} /> : <span className="text-[13px] text-ink-500">Not issued</span>}</td>
                <td className="text-right">{g.degree ? (
                  <div className="flex justify-end gap-1">
                    <button className="btn-secondary btn-sm" onClick={() => openBlob(`/api/v1/credentials/${g.degree.id}/certificate.pdf`)}>Certificate</button>
                    {!g.degree.revoked && <button className="btn-quiet btn-sm" onClick={async () => { await api.post(`/api/v1/credentials/${g.degree.id}/revoke`, { reason: "Revoked by the registrar" }); toast("Degree revoked"); grads.reload(); }}>Revoke</button>}
                  </div>) : <button className="btn-primary btn-sm" onClick={() => setSel(g)}>Issue degree</button>}</td>
              </tr>))}</tbody>
          </table></div>)}
      </Panel>
      <Modal open={!!sel} onClose={() => setSel(null)} title="Issue degree"
        footer={<><button className="btn-secondary" onClick={() => setSel(null)}>Cancel</button><button className="btn-primary" disabled={busy} onClick={issue}>{busy ? "Issuing…" : "Sign and issue"}</button></>}>
        {sel && <div className="space-y-4">
          <p className="text-sm text-ink-700">{sel.name} · {sel.program} · {sel.institution}</p>
          <div><label className="label" htmlFor="cl">Class awarded</label><select id="cl" className="input" value={form.class_awarded} onChange={(e) => setForm({ ...form, class_awarded: e.target.value })}>
            {["First Class with Distinction", "First Class", "Second Class", "Pass"].map((c) => <option key={c}>{c}</option>)}</select></div>
          <div><label className="label" htmlFor="cg">CGPA</label><input id="cg" className="input w-32" inputMode="decimal" value={form.cgpa} onChange={(e) => setForm({ ...form, cgpa: e.target.value })} />
            <p className="help">Optional. Not shared unless the graduate chooses to.</p></div>
          <ErrorText error={err} />
        </div>}
      </Modal>
    </div>
  );
}
