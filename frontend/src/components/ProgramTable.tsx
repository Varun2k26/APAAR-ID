import { fmt, pct, Tag } from "./ui";

/** Programme intake: regular seats against the approved intake; supernumerary seats against their own caps. */
export default function ProgramTable({ programs }: { programs: any[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr>
          <th>Programme</th><th className="num">Approved</th><th className="num">Regular</th><th className="num">Fill</th>
          <th className="num" title="Tuition fee waiver, cap 5% of approved intake">TFW</th>
          <th className="num" title="Foreign national / OCI / PIO, cap 15%">FN/OCI/PIO</th>
          <th className="num" title="Lateral entry, cap 10%">Lateral</th><th className="num">Total</th><th>Status</th>
        </tr></thead>
        <tbody>{programs.map((p) => {
          const v = Object.fromEntries((p.violations ?? []).map((x: any) => [x.bucket, x]));
          const cell = (bucket: string, n: number, cap?: number) => (
            <td className={`num ${v[bucket] ? "font-semibold text-red-700" : ""}`}>
              {fmt(n)}{cap != null && <span className="text-ink-400"> / {cap}</span>}</td>);
          return (
            <tr key={p.program_id}>
              <td><div className="font-medium">{p.name}</div><div className="text-xs text-ink-500">{p.code}{p.level ? ` · ${p.level}` : ""}</div></td>
              <td className="num">{fmt(p.approved)}</td>
              {cell("REGULAR", p.regular)}
              <td className="num">{pct(p.fill_rate)}</td>
              {cell("TFW", p.seats.TFW, p.caps.TFW)}{cell("FOREIGN", p.seats.FOREIGN, p.caps.FOREIGN)}{cell("LATERAL", p.seats.LATERAL, p.caps.LATERAL)}
              <td className="num font-medium">{fmt(p.total)}</td>
              <td>{p.violations?.length
                ? <Tag tone="red">{p.violations.map((x: any) => ({ R20: "Over intake", R21: "Over cap", R22: "NRI over cap" } as any)[x.code] ?? x.code).join(", ")}</Tag>
                : <Tag tone="green">Within limits</Tag>}</td>
            </tr>);
        })}</tbody>
      </table>
    </div>
  );
}
