import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Empty, ErrorText, Findings, Loading, Modal, PageHeader, Panel, Tabs, useAsync, useToast, when, Code } from "../../components/ui";
import StudentForm from "../../components/StudentForm";

export default function Issues() {
  const { user } = useAuth();
  const [tab, setTab] = useState("errors");
  const errors = useAsync(() => api.get("/api/v1/issues?severity=ERROR"), []);
  const warns = useAsync(() => api.get("/api/v1/issues?severity=WARN"), []);
  const programs = useAsync(() => api.get(`/api/v1/institutions/${user!.institution!.id}/programs/list`), []);
  const [fix, setFix] = useState<any>(null);
  const { toast, node } = useToast();

  const groups = useMemo(() => {
    const g = new Map<string, any>();
    (errors.data?.issues ?? []).forEach((i: any) => {
      const k = `${i.submission_id}-${i.row_number}`;
      if (!g.has(k)) g.set(k, { key: k, first: i, issues: [] as any[] });
      g.get(k).issues.push(i);
    });
    return [...g.values()];
  }, [errors.data]);
  const canFix = user?.permissions.includes("issue:fix");

  return (
    <div>
      {node}
      <PageHeader title="Corrections" description="Rows returned from your submissions, and warnings on accepted records." />
      <Tabs active={tab} onChange={setTab} tabs={[{ id: "errors", label: "Returned rows", count: groups.length }, { id: "warn", label: "Warnings", count: warns.data?.issues?.length ?? 0 }]} />
      {tab === "errors" && (
        <Panel flush>
          {errors.loading ? <Loading /> : errors.error ? <div className="p-4"><ErrorText error={errors.error} /></div> : !groups.length ? <Empty>No rows to correct.</Empty> : (
            <table className="tbl">
              <thead><tr><th>Submission</th><th>Student</th><th>Problems</th><th /></tr></thead>
              <tbody>{groups.map((g) => (
                <tr key={g.key}>
                  <td className="whitespace-nowrap"><div>Submission {g.first.submission_id}, row {g.first.row_number}</div><div className="text-xs text-ink-500">{when(g.first.created_at)}</div></td>
                  <td><div>{g.first.row_data?.name}</div><div className="mono text-xs text-ink-500">{g.first.row_data?.roll_no}</div></td>
                  <td><Findings findings={g.issues.map((i: any) => ({ code: i.rule_code, severity: "ERROR", message: i.message, hint: i.hint }))} /></td>
                  <td className="text-right">{canFix && <button className="btn-secondary btn-sm" onClick={() => setFix(g)}>Correct</button>}</td>
                </tr>))}</tbody>
            </table>)}
        </Panel>)}
      {tab === "warn" && (
        <Panel flush>
          {!warns.data?.issues?.length ? <Empty>No warnings.</Empty> : (
            <table className="tbl">
              <thead><tr><th>Rule</th><th>Detail</th><th>Raised</th><th /></tr></thead>
              <tbody>{warns.data.issues.map((i: any) => (
                <tr key={i.id}>
                  <td className="w-[220px]"><Code c={i.rule_code} severity="WARN" /> <span className="text-[13px] text-ink-600">{i.rule_title}</span></td>
                  <td className="text-[13px]">{i.message}{i.hint && <div className="text-ink-500">{i.hint}</div>}</td>
                  <td className="whitespace-nowrap text-[13px]">{when(i.created_at)}</td>
                  <td className="text-right">{canFix && <button className="btn-secondary btn-sm" onClick={async () => { await api.post(`/api/v1/issues/${i.id}/acknowledge`); warns.reload(); }}>Mark reviewed</button>}</td>
                </tr>))}</tbody>
            </table>)}
        </Panel>)}
      <Modal open={!!fix} onClose={() => setFix(null)} title={`Correct row ${fix?.first.row_number} of submission ${fix?.first.submission_id}`} wide>
        {fix && <FixForm group={fix} programs={programs.data ?? []} onDone={(r) => {
          toast(r.rejected ? "The row still has errors and has been returned again" : r.conflict ? "Accepted, but recorded as a duplicate enrolment" : "Row accepted", r.rejected ? "bad" : "good");
          setFix(null); errors.reload(); warns.reload();
        }} />}
      </Modal>
    </div>
  );
}

function FixForm({ group, programs, onDone }: { group: any; programs: any[]; onDone: (r: any) => void }) {
  const [row, setRow] = useState<Record<string, string>>({ ...group.first.row_data });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = group.issues.map((i: any) => i.field).filter(Boolean);
  return (
    <div className="space-y-5">
      <div className="rounded-sm border border-red-200 bg-red-50 px-4 py-3">
        <Findings findings={group.issues.map((i: any) => ({ code: i.rule_code, severity: "ERROR", message: i.message, hint: i.hint }))} />
      </div>
      <StudentForm row={row} onChange={setRow} programs={programs} highlight={fields} />
      <ErrorText error={err} />
      <div className="border-t border-ink-200 pt-4">
        <button className="btn-primary" disabled={busy} onClick={async () => { setBusy(true); try { onDone(await api.post(`/api/v1/issues/${group.first.id}/fix`, { row })); } catch (e: any) { setErr(e.message); } setBusy(false); }}>Resubmit row</button>
      </div>
    </div>
  );
}
