import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../lib/api";
import { DL, Empty, ErrorText, Loading, Modal, PageHeader, Panel, pct, Status, useAsync, useToast } from "../../components/ui";
import { STATE_NAME } from "../../components/IndiaTiles";

const KIND_LABEL: Record<string, string> = {
  INTAKE_EXCEEDED: "Admissions over approved intake", SUPERNUMERARY_EXCEEDED: "Supernumerary seats over cap", NRI_QUOTA_EXCEEDED: "NRI quota over cap",
  FILL_RATE_JUMP: "Sudden rise in fill rate", CATEGORY_SHIFT: "Change in category mix", PROVISIONAL_SHARE: "High share without APAAR",
  MULTIVARIATE: "Unusual overall profile",
};
const AXIS = { fontSize: 12, fill: "#5f6873", fontFamily: "IBM Plex Sans" };

export default function Anomalies() {
  const [params] = useSearchParams();
  const [filter, setFilter] = useState({ status: "", source: "", kind: params.get("kind") ?? "" });
  const q = new URLSearchParams(Object.entries(filter).filter(([, v]) => v)).toString();
  const list = useAsync(() => api.get(`/api/v1/anomalies?${q}`), [q]);
  const [sel, setSel] = useState<any>(null);
  const { toast, node } = useToast();
  const noteRef = useRef("");
  useEffect(() => {
    const f = Number(params.get("focus"));
    if (f && list.data) setSel(list.data.find((a: any) => a.id === f) ?? null);
  }, [list.data, params]);

  async function triage(status: string, note?: string) {
    await api.post(`/api/v1/anomalies/${sel.id}/triage`, { status, note });
    toast(`Marked as ${status.toLowerCase()}`); setSel(null); list.reload();
  }
  async function rerun() { const r = await api.post("/api/v1/anomalies/run"); toast(`Analysis complete: ${r.statistical + r.rule_alerts} findings`); list.reload(); }

  return (
    <div>
      {node}
      <PageHeader title="Anomalies" description="Rule findings are shared with the institution concerned. Statistical findings are visible to AICTE only."
        actions={<button className="btn-secondary" onClick={rerun}>Run analysis</button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <select className="input w-auto" value={filter.source} onChange={(e) => setFilter({ ...filter, source: e.target.value })} aria-label="Type">
          <option value="">All types</option><option value="RULE">Rule</option><option value="STATISTICAL">Statistical</option></select>
        <select className="input w-auto" value={filter.kind} onChange={(e) => setFilter({ ...filter, kind: e.target.value })} aria-label="Finding">
          <option value="">All findings</option>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="input w-auto" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })} aria-label="Status">
          <option value="">Any status</option>{["OPEN", "INVESTIGATING", "CONFIRMED", "DISMISSED"].map((s) => <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase()}</option>)}</select>
      </div>
      <Panel flush>
        {list.loading ? <Loading /> : list.error ? <div className="p-4"><ErrorText error={list.error} /></div> : !list.data?.length ? <Empty>No anomalies match these filters.</Empty> : (
          <div className="overflow-x-auto"><table className="tbl tbl-hover">
            <thead><tr><th>Institution</th><th>Finding</th><th>Type</th><th>Severity</th><th className="num">Score</th><th>Status</th></tr></thead>
            <tbody>{list.data.map((a: any) => (
              <tr key={a.id} onClick={() => setSel(a)}>
                <td className="min-w-[220px]"><div className="font-medium">{a.institution}</div><div className="text-xs text-ink-500">{a.institution_code} · {STATE_NAME[a.state] ?? a.state}</div></td>
                <td className="min-w-[280px]"><div className="text-ink-900">{a.title}</div><div className="text-xs text-ink-500">{KIND_LABEL[a.kind]}</div></td>
                <td><Status s={a.source} /></td><td><Status s={a.severity} /></td>
                <td className="num">{a.score.toFixed(2)}</td><td><Status s={a.status} /></td>
              </tr>))}</tbody>
          </table></div>)}
      </Panel>
      <Modal open={!!sel} onClose={() => setSel(null)} title={sel ? KIND_LABEL[sel.kind] : ""} wide
        footer={<>
          <button className="btn-secondary" onClick={() => triage("DISMISSED", noteRef.current)}>Dismiss</button>
          <button className="btn-secondary" onClick={() => triage("CONFIRMED", noteRef.current)}>Confirm</button>
          <button className="btn-primary" onClick={() => triage("INVESTIGATING", noteRef.current)}>Start investigation</button></>}>
        {sel && <Detail a={sel} onNote={(n) => (noteRef.current = n)} />}
      </Modal>
    </div>
  );
}

function Detail({ a, onNote }: { a: any; onNote: (n: string) => void }) {
  const [note, setNote] = useState(a.note ?? "");
  useEffect(() => { onNote(note); }, [note, onNote]);
  const x = a.explanation || {};
  return (
    <div className="space-y-5">
      <div>
        <div className="text-[15px] font-semibold">{a.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-500">
          <Link className="link" to={`/aicte/institutions/${a.institution_id}`}>{a.institution}</Link>
          <span>·</span><Status s={a.source} /><Status s={a.severity} /><Status s={a.status} />
        </div>
      </div>
      {x.summary && <p className="text-sm text-ink-800">{x.summary}</p>}
      {x.history_fill && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink-700">Fill rate by year</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={[...x.history_fill.map((v: number, i: number) => ({ y: `${2021 + i}`, v })), { y: "2026", v: x.current_fill }]} margin={{ left: 0, right: 8 }}>
              <CartesianGrid stroke="#eceef1" vertical={false} /><XAxis dataKey="y" tick={AXIS} tickLine={false} axisLine={{ stroke: "#dcdfe4" }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v) => pct(v)} domain={[0, 1]} width={40} />
              <Tooltip formatter={(v: number) => pct(v, 1)} contentStyle={{ fontSize: 12, borderRadius: 4 }} /><ReferenceLine y={1} stroke="#c3c8cf" />
              <Bar dataKey="v" name="Fill rate">{[...x.history_fill, x.current_fill].map((_: any, i: number) => <Cell key={i} fill={i === x.history_fill.length ? "#b54708" : "#9fb9dc"} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
          <DL rows={[["Deviation from own history", `${x.own_robust_z} (robust z-score)`], ["Deviation from state peers", `${x.peer_robust_z} (robust z-score)`]]} />
        </div>)}
      {x.moves && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink-700">Category shares</h3>
          <table className="tbl text-[13px]"><thead><tr><th>Category</th><th className="num">5-year history</th><th className="num">This year</th><th className="num">Change</th></tr></thead>
            <tbody>{x.moves.map((m: any) => (
              <tr key={m.category}><td>{m.category}</td><td className="num">{pct(m.history, 1)}</td><td className="num">{pct(m.current, 1)}</td>
                <td className={`num ${Math.abs(m.current - m.history) > 0.1 ? "font-semibold text-red-700" : ""}`}>{m.current >= m.history ? "+" : ""}{((m.current - m.history) * 100).toFixed(1)} pts</td></tr>))}</tbody></table>
        </div>)}
      {x.drivers && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink-700">Main factors</h3>
          <table className="tbl text-[13px]"><thead><tr><th>Measure</th><th className="num">This institution</th><th className="num">National median</th></tr></thead>
            <tbody>{x.drivers.map((d: any) => <tr key={d.feature}><td>{d.feature}</td><td className="num">{d.value}</td><td className="num">{d.median}</td></tr>)}</tbody></table>
        </div>)}
      {x.violations && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink-700">Seats</h3>
          <table className="tbl text-[13px]"><thead><tr><th>Category</th><th className="num">Admitted</th><th className="num">Limit</th></tr></thead>
            <tbody>{x.violations.map((v: any) => <tr key={v.bucket}><td>{v.bucket.charAt(0) + v.bucket.slice(1).toLowerCase()}</td><td className="num font-semibold text-red-700">{v.count}</td><td className="num">{v.limit}</td></tr>)}</tbody></table>
          <p className="help">Approved intake {x.approved}. Supernumerary seats are checked against their own caps.</p>
        </div>)}
      {x.pattern && <p className="border-l-2 border-ink-300 pl-3 text-[13px] text-ink-600">{x.pattern}</p>}
      <div>
        <label className="label" htmlFor="note">Note</label>
        <textarea id="note" className="input h-16" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Recorded in the audit log" />
      </div>
    </div>
  );
}
