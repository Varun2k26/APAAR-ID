import { useState } from "react";
import { api } from "../../lib/api";
import { Alert, day, DL, PageHeader, Panel, Status, useAsync, useToast, when } from "../../components/ui";

const CAP_LABEL: Record<string, string> = { TFW: "Tuition fee waiver", FOREIGN: "Foreign national / OCI / PIO", LATERAL: "Lateral entry", NRI: "NRI (within intake)" };

export default function SystemPage() {
  const meta = useAsync(() => api.get("/api/v1/meta"), []);
  const ctl = useAsync(() => api.get("/mock/apaar/control"), []);
  const census = useAsync(() => api.get("/api/v1/census"), []);
  const { toast, node } = useToast();
  const [busy, setBusy] = useState(false);
  async function setRegistry(down: boolean) {
    await api.post("/mock/apaar/control", { down, latency_ms: 0, fail_rate: 0 });
    ctl.reload(); toast(down ? "Registry connection disabled" : "Registry connection restored");
  }
  async function syncApprovals() {
    setBusy(true);
    const feed = await api.get(`/mock/aicte/approvals?year=${meta.data.academic_year}`);
    const r = await api.post("/api/v1/aicte/approvals/import", { year: meta.data.academic_year, approvals: feed.approvals });
    toast(`${r.rows} approvals imported, ${r.changed} changed`); setBusy(false);
  }
  const m = meta.data;
  return (
    <div className="space-y-6">
      {node}
      <PageHeader title="Administration" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="APAAR registry connection" description="Simulated in this prototype">
          {ctl.data && <DL rows={[
            ["Status", <Status s={ctl.data.down ? "FAILED" : "ACTIVE"} label={ctl.data.down ? "Unavailable" : "Available"} />],
            ["Circuit breaker", ctl.data.client_breaker.open ? "Open: requests are not being sent" : "Closed"],
            ["Consecutive failures", ctl.data.client_breaker.consecutive_failures],
            ["Cached lookups", ctl.data.client_breaker.cached_ids],
          ]} />}
          <p className="help mt-3">While the registry is unavailable, submissions are accepted as pending and checked again automatically.</p>
          <div className="mt-3 flex gap-2">
            <button className="btn-secondary" onClick={() => setRegistry(true)}>Simulate outage</button>
            <button className="btn-secondary" onClick={() => setRegistry(false)}>Restore</button>
          </div>
        </Panel>
        <Panel title="Approved intake" description="Imported from the AICTE approval process">
          <p className="text-sm text-ink-700">Sanctioned intake for every programme is taken from the approval feed rather than entered by institutions.</p>
          <button className="btn-primary mt-4" disabled={busy || !m} onClick={syncApprovals}>{busy ? "Importing…" : `Import approvals for ${m?.label ?? ""}`}</button>
        </Panel>
        <Panel title="Admission calendar">
          {m && <DL rows={[["Academic year", m.label], ["Admissions open", day(m.admission_open)], ["Last date of admission", day(m.admission_cutoff)],
            ["Census date", day(m.census_date)], ["Intake checks", m.census_binding ? "Binding (census frozen)" : "Provisional until census"]]} />}
          <div className="mt-4 flex items-center gap-3">
            <button className="btn-secondary" onClick={async () => { const r = await api.post("/api/v1/census/freeze"); toast(`Snapshot recorded: ${r.students.toLocaleString("en-IN")} students`); census.reload(); }}>Record census snapshot</button>
          </div>
          {(census.data ?? []).length > 0 && <table className="tbl mt-4 text-[13px]"><thead><tr><th>Snapshot</th><th>Recorded</th><th className="num">Students</th><th>By</th></tr></thead>
            <tbody>{census.data.map((c: any) => <tr key={c.id}><td>#{c.id}</td><td>{when(c.frozen_at)}</td><td className="num">{c.students.toLocaleString("en-IN")}</td><td>{c.frozen_by}</td></tr>)}</tbody></table>}
        </Panel>
        <Panel title="Policy">
          {m && <>
            <h3 className="mb-1 text-[13px] font-semibold text-ink-700">Seat caps (share of approved intake)</h3>
            <DL rows={Object.entries(m.caps).map(([k, v]: any) => [CAP_LABEL[k] ?? k, `${Math.round(v * 100)}%`])} />
            <h3 className="mb-1 mt-4 text-[13px] font-semibold text-ink-700">Concurrent enrolment</h3>
            <DL rows={Object.entries(m.dual_policy).filter(([k]: any) => k.startsWith("REGULAR")).map(([k, v]: any) =>
              [k.replace("+", " with ").toLowerCase().replace(/^./, (c: string) => c.toUpperCase()), v === "CONFLICT" ? "Not permitted" : "Permitted"])} />
          </>}
          <Alert className="mt-4" tone="warn">Cap values must be confirmed against the current AICTE Approval Process Handbook.</Alert>
        </Panel>
      </div>
    </div>
  );
}
