// Tile-grid map of India: one square per state, placed roughly where it sits geographically.
const TILES: Record<string, [number, number, string]> = {
  JK: [3, 0, "Jammu & Kashmir"], LA: [4, 0, "Ladakh"], PB: [2, 1, "Punjab"], HP: [3, 1, "Himachal Pradesh"], UK: [4, 1, "Uttarakhand"],
  RJ: [1, 2, "Rajasthan"], HR: [2, 2, "Haryana"], DL: [3, 2, "Delhi"], UP: [4, 2, "Uttar Pradesh"], BR: [5, 2, "Bihar"],
  SK: [6, 1, "Sikkim"], AR: [8, 1, "Arunachal Pradesh"], AS: [7, 2, "Assam"], NL: [8, 2, "Nagaland"],
  GJ: [0, 3, "Gujarat"], MP: [2, 3, "Madhya Pradesh"], CT: [3, 3, "Chhattisgarh"], JH: [4, 3, "Jharkhand"], WB: [5, 3, "West Bengal"],
  ML: [7, 3, "Meghalaya"], MN: [8, 3, "Manipur"], MH: [1, 4, "Maharashtra"], TS: [2, 4, "Telangana"], OD: [4, 4, "Odisha"],
  TR: [6, 3, "Tripura"], MZ: [7, 4, "Mizoram"], GA: [1, 5, "Goa"], KA: [2, 5, "Karnataka"], AP: [3, 5, "Andhra Pradesh"],
  KL: [2, 6, "Kerala"], TN: [3, 6, "Tamil Nadu"],
};
export const STATE_NAME = Object.fromEntries(Object.entries(TILES).map(([k, v]) => [k, v[2]]));

export type StateRow = { state: string; students: number; approved: number; fill: number | null; anomalies: number; institutions: number; provisional: number };

// Sequential blue ramp, light to dark.
const RAMP = ["#e3ebf5", "#c6d6ea", "#9fb9dc", "#7097c8", "#4775b0", "#245693", "#0f3e7a"];

export default function IndiaTiles({ rows, metric, onPick, selected }:
  { rows: StateRow[]; metric: "students" | "fill" | "anomalies"; onPick?: (s: string) => void; selected?: string | null }) {
  const by = Object.fromEntries(rows.map((r) => [r.state, r]));
  const val = (r: StateRow) => (metric === "fill" ? r.fill ?? 0 : (r[metric] as number));
  const vals = rows.map(val);
  const max = Math.max(...vals, 1e-9), min = metric === "anomalies" ? 0 : Math.min(...vals);
  const bucket = (v: number) => Math.min(RAMP.length - 1, Math.floor(((v - min) / (max - min || 1)) * (RAMP.length - 1) + 1e-9));
  const S = 46, G = 3;
  const label = (v: number) => metric === "fill" ? `${Math.round(v * 100)}%` : metric === "students" ? (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)) : String(v);
  return (
    <div>
      <svg viewBox={`0 0 ${9 * (S + G)} ${7 * (S + G)}`} className="mx-auto w-full max-w-[440px]" role="img" aria-label="Map of states">
        {Object.entries(TILES).map(([code, [c, r, name]]) => {
          const d = by[code];
          const v = d ? val(d) : null;
          const b = v == null ? -1 : bucket(v);
          const fill = b < 0 ? "#f3f4f6" : RAMP[b];
          const dark = b >= 4;
          return (
            <g key={code} transform={`translate(${c * (S + G)}, ${r * (S + G)})`} className={d ? "cursor-pointer" : ""} onClick={() => d && onPick?.(code)}>
              <title>{name}{d ? ` — ${d.institutions} institutions, ${d.students.toLocaleString("en-IN")} students, fill ${d.fill != null ? Math.round(d.fill * 100) + "%" : "—"}, ${d.anomalies} open anomalies` : " — not in this dataset"}</title>
              <rect width={S} height={S} rx={2} fill={fill} stroke={selected === code ? "#14181d" : "none"} strokeWidth={2} />
              <text x={6} y={15} fontSize="10.5" fontWeight={600} fill={b < 0 ? "#b5bcc5" : dark ? "white" : "#14181d"} fontFamily="IBM Plex Sans">{code}</text>
              {v != null && <text x={6} y={S - 8} fontSize="10" fill={dark ? "#dbe6f4" : "#343b44"} fontFamily="IBM Plex Sans">{label(v)}</text>}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex items-center justify-center gap-2 text-2xs text-ink-500">
        <span>{metric === "fill" ? pctLabel(min) : Math.round(min)}</span>
        <span className="flex">{RAMP.map((c) => <span key={c} className="h-2 w-6" style={{ background: c }} />)}</span>
        <span>{metric === "fill" ? pctLabel(max) : max >= 1000 ? `${(max / 1000).toFixed(1)}k` : Math.round(max)}</span>
      </div>
    </div>
  );
}
const pctLabel = (v: number) => `${Math.round(v * 100)}%`;
