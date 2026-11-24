import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../lib/api";
import { ErrorText, fmt, Loading, PageHeader, Panel, pct, useAsync } from "../../components/ui";
import { STATE_NAME } from "../../components/IndiaTiles";

const TYPE: Record<string, string> = { PRIVATE: "Private", GOVT: "Government", AIDED: "Aided" };

export default function Institutions() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const state = params.get("state") ?? "";
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("anomalies");
  const list = useAsync(() => api.get(`/api/v1/analytics/institutions?sort=${sort}${state ? `&state=${state}` : ""}`), [state, sort]);
  const rows = (list.data ?? []).filter((r: any) => !q || `${r.name} ${r.code}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <PageHeader title="Institutions" description={state ? STATE_NAME[state] : "All approved institutions reporting for the current academic year."} />
      <div className="mb-4 flex flex-wrap gap-2">
        <input className="input max-w-xs" placeholder="Search by name or AICTE code" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <select className="input w-auto" value={state} onChange={(e) => setParams(e.target.value ? { state: e.target.value } : {})} aria-label="State">
          <option value="">All states</option>{["AP", "DL", "GJ", "KA", "KL", "MP", "MH", "RJ", "TN", "TS", "UP", "WB"].map((s) => <option key={s} value={s}>{STATE_NAME[s]}</option>)}</select>
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="anomalies">Sort by open anomalies</option><option value="students">Sort by students</option><option value="fill">Sort by fill rate</option><option value="name">Sort by name</option></select>
      </div>
      <Panel flush>
        {list.loading ? <Loading /> : list.error ? <div className="p-4"><ErrorText error={list.error} /></div> : (
          <div className="overflow-x-auto"><table className="tbl tbl-hover">
            <thead><tr><th>Institution</th><th>State</th><th>Type</th><th className="num">Programmes</th><th className="num">Approved</th>
              <th className="num">Students</th><th className="num">Fill</th><th className="num">Without APAAR</th><th className="num">Anomalies</th></tr></thead>
            <tbody>{rows.map((r: any) => (
              <tr key={r.id} onClick={() => nav(`/aicte/institutions/${r.id}`)}>
                <td><div className="font-medium text-brand-700">{r.name}</div><div className="text-xs text-ink-500">{r.code}</div></td>
                <td>{STATE_NAME[r.state] ?? r.state}</td><td>{TYPE[r.type] ?? r.type}</td>
                <td className="num">{r.programs}</td><td className="num">{fmt(r.approved)}</td><td className="num">{fmt(r.students)}</td>
                <td className={`num ${r.fill > 1 ? "font-semibold text-red-700" : ""}`}>{pct(r.fill)}</td>
                <td className={`num ${r.provisional_share > 0.15 ? "font-semibold text-red-700" : ""}`}>{pct(r.provisional_share, 1)}</td>
                <td className={`num ${r.anomalies ? "font-semibold text-red-700" : "text-ink-400"}`}>{r.anomalies}</td>
              </tr>))}</tbody>
          </table></div>)}
        {list.data && <div className="border-t border-ink-200 px-4 py-2.5 text-[13px] text-ink-500">{rows.length} institutions</div>}
      </Panel>
    </div>
  );
}
