import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Alert, Empty, PageHeader, Panel, Status, useAsync, useToast, when } from "../../components/ui";

const EVENT: Record<string, string> = {
  ISSUE_RAISED: "Row returned", CONFLICT_OPENED: "Duplicate enrolment", CONFLICT_RESOLVED: "Duplicate resolved", CONSENT_REQUESTED: "Consent requested",
  CONSENT_DECIDED: "Consent decided", TRANSFER_REQUESTED: "Transfer requested", TRANSFER_COMPLETED: "Transfer completed",
  SUBMISSION_PROCESSED: "Submission processed", CORRECTION_REQUESTED: "Correction requested", INTAKE_ALERT: "Intake alert",
};

export default function Integration() {
  const { user } = useAuth();
  const keys = useAsync(() => api.get("/api/v1/integration/api-keys"), []);
  const hooks = useAsync(() => api.get("/api/v1/integration/webhooks"), []);
  const received = useAsync(() => api.get(`/mock/erp/${user!.institution!.id}/received`), []);
  const [newKey, setNewKey] = useState<any>(null);
  const [label, setLabel] = useState("Campus ERP");
  const { toast, node } = useToast();
  const origin = window.location.origin;
  const curl = `curl -X POST ${origin}/api/v1/enrollments/batch \\
  -H "X-API-Key: <your key>" \\
  -H "Idempotency-Key: admissions-2026-batch-7" \\
  -H "Content-Type: application/json" \\
  -d '{"records": [{"roll_no": "26CSE500", "apaar_id": "...", "name": "...",
        "dob": "2008-01-01", "gender": "F", "program_code": "BTECH-CSE",
        "admission_date": "2026-11-20", "seat_type": "MERIT",
        "social_category": "GEN", "nationality": "INDIAN"}]}'`;
  return (
    <div className="space-y-6">
      {node}
      <PageHeader title="Integration" description="Connect your ERP to submit records automatically and receive notifications."
        actions={<a className="btn-secondary" href="/docs" target="_blank" rel="noreferrer">API documentation</a>} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="API keys" description="Keys are limited to your institution. Only a hash of each key is stored.">
          <div className="flex gap-2">
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Key name" />
            <button className="btn-primary" onClick={async () => { setNewKey(await api.post("/api/v1/integration/api-keys", { label })); keys.reload(); }}>Create key</button>
          </div>
          {newKey && <Alert className="mt-3" tone="success" title="Copy this key now. It will not be shown again.">
            <div className="mt-1 flex items-center gap-2"><code className="mono break-all text-ink-900">{newKey.key}</code>
              <button className="btn-secondary btn-sm" onClick={() => { navigator.clipboard?.writeText(newKey.key); toast("Copied"); }}>Copy</button></div></Alert>}
          <table className="tbl mt-4 text-[13px]"><thead><tr><th>Name</th><th>Key</th><th>Last used</th><th /></tr></thead>
            <tbody>{(keys.data ?? []).map((k: any) => (
              <tr key={k.id}><td>{k.label}</td><td className="mono">{k.prefix}…</td><td>{when(k.last_used_at)}</td>
                <td className="text-right">{k.revoked ? <Status s="REVOKED" /> : <button className="btn-quiet btn-sm" onClick={async () => { await api.del(`/api/v1/integration/api-keys/${k.id}`); keys.reload(); }}>Revoke</button>}</td></tr>))}</tbody></table>
        </Panel>
        <Panel title="Submitting records" description="Repeating a request with the same Idempotency-Key returns the original result. Gzip request bodies are accepted.">
          <pre className="overflow-x-auto rounded-sm bg-ink-900 p-4 text-xs leading-relaxed text-ink-100"><code className="mono">{curl}</code></pre>
        </Panel>
      </div>
      <Panel title="Webhooks" description="Notifications are signed with HMAC-SHA256 in the X-Registry-Signature header and retried on failure."
        actions={<button className="btn-secondary btn-sm" onClick={async () => { const r = await api.post("/api/v1/integration/webhooks", {}); toast(`Webhook added. Signing secret: ${r.secret}`); hooks.reload(); }}>Add webhook</button>} flush>
        {(hooks.data?.webhooks ?? []).length === 0 ? <Empty>No webhooks configured.</Empty> : (hooks.data.webhooks.map((h: any) => (
          <div key={h.id} className="border-b border-ink-200 last:border-0">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <span className="mono break-all text-[13px]">{h.url}</span><span className="text-xs text-ink-500">{h.event_types.length} event types · secret {h.secret_hint}</span>
            </div>
            {h.deliveries.length > 0 && <table className="tbl text-[13px]"><thead><tr><th>Event</th><th>Delivery</th><th className="num">Attempts</th><th>Response</th></tr></thead>
              <tbody>{h.deliveries.map((d: any) => (
                <tr key={d.id}><td>{EVENT[d.event_type] ?? d.event_type}</td><td><Status s={d.status} /></td><td className="num">{d.attempts}</td>
                  <td className="text-ink-600">{d.response_code ? `HTTP ${d.response_code}` : d.last_error ?? "—"}</td></tr>))}</tbody></table>}
          </div>)))}
      </Panel>
      <Panel title="Received by your ERP" description="Simulated ERP endpoint for this prototype" flush>
        {!received.data?.length ? <Empty>Nothing received yet.</Empty> : (
          <table className="tbl text-[13px]"><thead><tr><th>Received</th><th>Event</th><th>Signature</th><th>Payload</th></tr></thead>
            <tbody>{received.data.slice(0, 10).map((r: any) => (
              <tr key={r.id}><td className="whitespace-nowrap">{when(r.received_at)}</td><td>{EVENT[r.event_type] ?? r.event_type}</td>
                <td><Status s={r.signature_valid ? "VALID" : "INVALID"} label={r.signature_valid ? "Valid" : "Invalid"} /></td>
                <td className="mono max-w-[420px] truncate text-xs text-ink-600">{JSON.stringify(r.body.data)}</td></tr>))}</tbody></table>)}
      </Panel>
    </div>
  );
}
