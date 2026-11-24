import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../../lib/api";
import { parseCsv, precheck } from "../../lib/csv";
import { Alert, ErrorText, Findings, Loading, PageHeader, Panel, Stats, Status, useAsync } from "../../components/ui";

export default function Upload() {
  const demo = useAsync(() => api.get("/api/v1/dev/demo-accounts").catch(() => null), []);
  const [file, setFile] = useState<File | null>(null);
  const [pre, setPre] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function pick(f: File | null) {
    setFile(f); setReport(null); setErr(null); setPre(null);
    if (!f) return;
    const { headers, rows } = parseCsv(await f.text());
    setPre({ headers, rows, ...precheck(rows, headers) });
  }
  async function loadDemo(name: string) {
    const b = await api.blob(`/api/v1/dev/demo-files/${name}`);
    pick(new File([b], name, { type: "text/csv" }));
  }
  async function send() {
    if (!file) return;
    setBusy(true); setErr(null);
    try { setReport(await api.upload("/api/v1/enrollments/upload", file)); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  const flagged = pre ? pre.problems.filter((p: string[]) => p.length).length : 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Upload students" description="Submit a CSV file using the standard template. Rows that pass are accepted; rows with errors are returned for correction. Re-submitting a roll number updates that student."
        actions={<button className="btn-secondary" onClick={() => download("/api/v1/templates/enrollments.csv", "enrollment_template.csv")}>Download template</button>} />
      <Panel>
        <div className="flex flex-wrap items-center gap-3">
          <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" id="csv" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          <label htmlFor="csv" className="btn-primary cursor-pointer">Choose file</label>
          <span className="text-sm text-ink-600">{file ? `${file.name} (${(file.size / 1024).toFixed(1)} KB)` : "No file selected"}</span>
          {demo.data?.demo_files && (
            <span className="ml-auto flex flex-wrap items-center gap-2 text-[13px] text-ink-500">Sample files:
              {demo.data.demo_files.map((n: string) => <button key={n} className="link" onClick={() => loadDemo(n)}>{n}</button>)}</span>)}
        </div>
      </Panel>

      {pre && !report && (
        <Panel title={`${pre.rows.length} rows read`} description={flagged ? `${flagged} rows have problems that will be returned. Full checks run on submission.` : "No problems found in the file. Full checks run on submission."}
          actions={<button className="btn-primary" disabled={busy || pre.missingCols.length > 0} onClick={send}>{busy ? "Submitting…" : `Submit ${pre.rows.length} rows`}</button>} flush>
          {pre.missingCols.length > 0 && <div className="p-4"><Alert tone="error" title="Missing columns">{pre.missingCols.join(", ")}. Use the template.</Alert></div>}
          <div className="max-h-[360px] overflow-auto"><table className="tbl text-[13px]">
            <thead><tr><th className="num">Row</th><th>Roll no.</th><th>Name</th><th>APAAR ID</th><th>Programme</th><th>File check</th></tr></thead>
            <tbody>{pre.rows.map((r: any, i: number) => (
              <tr key={i}><td className="num text-ink-500">{i + 1}</td><td className="mono">{r.roll_no}</td><td>{r.name}</td>
                <td className="mono">{r.apaar_id || <span className="font-sans text-ink-500">Not provided</span>}</td><td>{r.program_code}</td>
                <td>{pre.problems[i].length ? <span className="text-red-700">{pre.problems[i].join("; ")}</span> : <span className="text-ink-500">OK</span>}</td></tr>))}</tbody>
          </table></div>
        </Panel>)}
      {busy && <Loading label="Checking against the APAAR registry and other institutions…" />}
      <ErrorText error={err} />
      {report && <Report r={report} />}
    </div>
  );
}

const OUTCOME: Record<string, string> = { CREATED: "Accepted", UPDATED: "Updated", UNCHANGED: "Unchanged", REJECTED: "Returned", CONFLICT: "Duplicate" };
const OUTCOME_TONE: Record<string, string> = { CREATED: "ACTIVE", UPDATED: "UPDATED", UNCHANGED: "UNCHANGED", REJECTED: "ERROR", CONFLICT: "CONFLICT" };

export function Report({ r }: { r: any }) {
  return (
    <Panel title={`Submission ${r.submission_id}`} description={r.replayed ? "This submission was already processed; the earlier result is shown." : undefined}
      actions={r.rejected > 0 && <button className="btn-secondary btn-sm" onClick={() => download(`/api/v1/submissions/${r.submission_id}/errors.csv`, `submission_${r.submission_id}_returned.csv`)}>Download returned rows</button>} flush>
      <div className="p-4">
        <Stats items={[
          { label: "Accepted", value: r.created }, { label: "Updated", value: r.updated },
          { label: "Returned for correction", value: r.rejected, tone: r.rejected ? "bad" : "default" },
          { label: "Duplicate enrolments", value: r.conflict, tone: r.conflict ? "bad" : "default" },
          { label: "Warnings", value: r.warnings, tone: r.warnings ? "warn" : "default" },
        ]} />
        {r.intake_alerts?.map((a: any, i: number) => <Alert key={i} className="mt-3" tone="warn">{a.title}</Alert>)}
      </div>
      {r.rows?.length > 0 && (
        <div className="overflow-x-auto border-t border-ink-200"><table className="tbl">
          <thead><tr><th className="num">Row</th><th>Roll no.</th><th>Result</th><th>Details</th></tr></thead>
          <tbody>{r.rows.map((x: any) => (
            <tr key={x.row}><td className="num text-ink-500">{x.row}</td><td><div className="mono">{x.roll_no}</div>{x.person_ref && <div className="mono text-xs text-ink-500">{x.person_ref}</div>}</td>
              <td><Status s={OUTCOME_TONE[x.outcome]} label={OUTCOME[x.outcome]} /></td><td><Findings findings={x.findings} /></td></tr>))}</tbody>
        </table></div>)}
      {r.rejected > 0 && <div className="border-t border-ink-200 px-4 py-3 text-[13px] text-ink-600">Returned rows are listed under <Link className="link" to="/institution/issues">Corrections</Link>, where they can be fixed and resubmitted individually.</div>}
    </Panel>
  );
}
