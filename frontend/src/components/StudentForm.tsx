import { apaarCheck } from "../lib/csv";

export const EMPTY_ROW: Record<string, string> = {
  roll_no: "", apaar_id: "", name: "", dob: "", gender: "F", parent_name: "", qualifying_exam_roll: "", program_code: "",
  admission_date: new Date().toISOString().slice(0, 10), year_of_study: "1", mode: "REGULAR", seat_type: "MERIT",
  social_category: "GEN", nationality: "INDIAN",
};
const OPTS: Record<string, [string, string][]> = {
  gender: [["F", "Female"], ["M", "Male"], ["O", "Other"]],
  mode: [["REGULAR", "Regular"], ["ODL", "Open and distance learning"], ["ONLINE", "Online"]],
  seat_type: [["MERIT", "Merit"], ["MANAGEMENT", "Management"], ["NRI", "NRI"], ["TFW", "Tuition fee waiver (supernumerary)"],
              ["FOREIGN", "FN / OCI / PIO (supernumerary)"], ["LATERAL", "Lateral entry (supernumerary)"]],
  social_category: [["GEN", "General"], ["EWS", "EWS"], ["OBC-NCL", "OBC (non-creamy layer)"], ["SC", "SC"], ["ST", "ST"]],
  nationality: [["INDIAN", "Indian"], ["NRI", "NRI"], ["OCI", "OCI"], ["PIO", "PIO"], ["FOREIGN_NATIONAL", "Foreign national"]],
  year_of_study: [["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"]],
};
const SECTIONS: [string, string[]][] = [
  ["Student", ["name", "dob", "gender", "parent_name", "apaar_id", "qualifying_exam_roll"]],
  ["Admission", ["roll_no", "program_code", "admission_date", "year_of_study", "mode"]],
  ["Category", ["seat_type", "social_category", "nationality"]],
];
const LABELS: Record<string, string> = {
  roll_no: "Roll number", apaar_id: "APAAR ID", name: "Full name", dob: "Date of birth", gender: "Gender",
  parent_name: "Parent or guardian", qualifying_exam_roll: "Qualifying exam roll number", program_code: "Programme",
  admission_date: "Date of admission", year_of_study: "Year of study", mode: "Mode of study", seat_type: "Seat type",
  social_category: "Social category", nationality: "Nationality",
};
const HELP: Record<string, string> = { apaar_id: "Leave blank if not yet issued. A provisional ID will be assigned." };

export default function StudentForm({ row, onChange, programs, highlight }:
  { row: Record<string, string>; onChange: (r: Record<string, string>) => void; programs: { code: string; name: string }[]; highlight?: string[] }) {
  const set = (k: string, v: string) => onChange({ ...row, [k]: v });
  const apaarErr = apaarCheck(row.apaar_id ?? "");
  return (
    <div className="space-y-6">
      {SECTIONS.map(([title, keys]) => (
        <fieldset key={title}>
          <legend className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-ink-500">{title}</legend>
          <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {keys.map((k) => {
              const hl = highlight?.includes(k) ? "border-red-600 ring-2 ring-red-100" : "";
              const v = String(row[k] ?? "");
              return (
                <div key={k}>
                  <label className="label" htmlFor={`f-${k}`}>{LABELS[k]}</label>
                  {k === "program_code" ? (
                    <select id={`f-${k}`} className={`input ${hl}`} value={v} onChange={(e) => set(k, e.target.value)}>
                      <option value="">Select a programme</option>
                      {programs.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                      {v && !programs.some((p) => p.code === v) && <option value={v}>{v} (not approved)</option>}
                    </select>
                  ) : OPTS[k] ? (
                    <select id={`f-${k}`} className={`input ${hl}`} value={v} onChange={(e) => set(k, e.target.value)}>
                      {v && !OPTS[k].some(([o]) => o === v) && <option value={v}>{v} (invalid)</option>}
                      {OPTS[k].map(([o, l]) => <option key={o} value={o}>{l}</option>)}
                    </select>
                  ) : (
                    <input id={`f-${k}`} className={`input ${k === "apaar_id" || k === "roll_no" ? "mono" : ""} ${hl}`}
                      type={k === "dob" || k === "admission_date" ? "date" : "text"} value={v} onChange={(e) => set(k, e.target.value)} />
                  )}
                  {k === "apaar_id" && v && apaarErr ? <p className="mt-1 text-xs text-red-700">{apaarErr}</p>
                    : HELP[k] && <p className="help">{HELP[k]}</p>}
                </div>);
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
