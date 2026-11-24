import { useState } from "react";
import { api } from "../../lib/api";
import { Alert, ErrorText, fmt, Loading, PageHeader, Panel, useAsync, when } from "../../components/ui";

const ACTIONS = ["RECORD_READ", "RECORD_READ_DENIED", "ENROLLMENT_CREATE", "ENROLLMENT_UPDATE", "ENROLLMENT_STATUS", "SUBMISSION",
  "CONFLICT_RESOLVE", "CONSENT_APPROVE", "CONSENT_REVOKE", "VERIFY_ONLINE", "AUDIT_QUERY", "INCLUDED_IN_AUDIT", "CREDENTIAL_ISSUE",
  "CREDENTIAL_REVOKE", "LOGIN", "ANOMALY_TRIAGE"];
const label = (a: string) => a.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

export default function Audit() {
  const [action, setAction] = useState("");
  const log = useAsync(() => api.get(`/api/v1/audit?limit=150${action ? `&action=${action}` : ""}`), [action]);
  const [check, setCheck] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <PageHeader title="Audit log" description="Every change, record access and verification. Each entry is chained to the previous one by its hash, so altering or removing an entry is detectable."
        actions={<button className="btn-primary" disabled={busy} onClick={async () => { setBusy(true); setCheck(await api.get("/api/v1/audit/verify")); setBusy(false); }}>
          {busy ? "Checking…" : "Check integrity"}</button>} />
      {check && <Alert className="mb-4" tone={check.ok ? "success" : "error"} title={check.ok ? "Integrity check passed" : "Integrity check failed"}>
        {check.ok ? `All ${fmt(check.entries_checked)} entries are intact.` : `Entry #${check.broken_at}: ${check.reason}`}</Alert>}
      <div className="mb-4">
        <select className="input w-auto" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
          <option value="">All actions</option>{ACTIONS.map((a) => <option key={a} value={a}>{label(a)}</option>)}</select>
      </div>
      <Panel flush>
        {log.loading ? <Loading /> : log.error ? <div className="p-4"><ErrorText error={log.error} /></div> : (
          <div className="overflow-x-auto"><table className="tbl text-[13px]">
            <thead><tr><th className="num">#</th><th>Time</th><th>User</th><th>Action</th><th>Record</th><th>Reason</th><th>Hash</th></tr></thead>
            <tbody>{log.data.entries.map((e: any) => (
              <tr key={e.id}>
                <td className="num text-ink-500">{e.id}</td><td className="whitespace-nowrap">{when(e.at)}</td>
                <td><div>{e.actor}</div><div className="text-xs text-ink-500">{label(e.role)}</div></td>
                <td className="whitespace-nowrap">{label(e.action)}</td>
                <td className="mono text-xs">{e.resource}</td>
                <td className="max-w-[260px] text-ink-600">{e.purpose ?? "—"}</td>
                <td className="mono text-xs text-ink-500" title={`previous ${e.prev_hash}`}>{e.hash}</td>
              </tr>))}</tbody>
          </table></div>)}
        {log.data && <div className="border-t border-ink-200 px-4 py-2.5 text-[13px] text-ink-500">Showing latest {log.data.entries.length} of {fmt(log.data.total)} entries</div>}
      </Panel>
    </div>
  );
}
