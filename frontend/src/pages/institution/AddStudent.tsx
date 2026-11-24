import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ErrorText, PageHeader, Panel, useAsync } from "../../components/ui";
import StudentForm, { EMPTY_ROW } from "../../components/StudentForm";
import { Report } from "./Upload";

const KEY = "spine.draft.student";

export default function AddStudent() {
  const { user } = useAuth();
  const programs = useAsync(() => api.get(`/api/v1/institutions/${user!.institution!.id}/programs/list`), []);
  const [row, setRow] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(KEY) ?? "") || EMPTY_ROW; } catch { return EMPTY_ROW; }
  });
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(row)); } catch { /* private mode */ } }, [row]);
  async function submit() {
    setErr(null); setBusy(true);
    try {
      const r = await api.post("/api/v1/enrollments", row);
      setReport(r);
      if (!r.rejected) { setRow(EMPTY_ROW); try { localStorage.removeItem(KEY); } catch { /* */ } }
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <div className="space-y-6">
      <PageHeader title="Add a student" description="For institutions without an ERP or file export. Your entries are saved on this device until submitted." />
      <Panel>
        <StudentForm row={row} onChange={setRow} programs={programs.data ?? []} />
        <div className="mt-6 flex gap-2 border-t border-ink-200 pt-4">
          <button className="btn-primary" disabled={busy} onClick={submit}>{busy ? "Submitting…" : "Submit"}</button>
          <button className="btn-secondary" onClick={() => setRow(EMPTY_ROW)}>Clear form</button>
        </div>
      </Panel>
      <ErrorText error={err} />
      {report && <Report r={report} />}
    </div>
  );
}
