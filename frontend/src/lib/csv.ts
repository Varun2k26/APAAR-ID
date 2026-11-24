// Client-side CSV parsing + pre-validation, so a college on a weak connection catches most
// mistakes before uploading anything. The server re-validates everything; this is a convenience.
const D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
  [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]];
const P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],
  [4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]];

export function apaarCheck(raw: string): string | null {
  const s = (raw || "").replace(/[\s-]/g, "");
  if (!s) return null;
  if (!/^\d+$/.test(s)) return "APAAR must be digits";
  if (s.length !== 12) return `APAAR must be 12 digits (got ${s.length})`;
  let c = 0;
  s.split("").reverse().forEach((ch, i) => { c = D[c][P[i % 8][Number(ch)]]; });
  return c === 0 ? null : "APAAR check digit fails (typo or swapped digits)";
}

export function parseCsv(text: string): { headers: string[]; rows: Record<string, string>[] } {
  const out: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((c) => c.trim() !== "")) out.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell || row.length) { row.push(cell); if (row.some((c) => c.trim())) out.push(row); }
  const headers = (out.shift() ?? []).map((h) => h.trim().toLowerCase().replace(/^﻿/, ""));
  return { headers, rows: out.map((r) => Object.fromEntries(headers.map((h, i) => [h, (r[i] ?? "").trim()]))) };
}

const ENUMS: Record<string, string[]> = {
  gender: ["M", "F", "O"], seat_type: ["MERIT", "MANAGEMENT", "NRI", "TFW", "FOREIGN", "LATERAL"],
  social_category: ["GEN", "EWS", "OBC-NCL", "SC", "ST"], nationality: ["INDIAN", "NRI", "OCI", "PIO", "FOREIGN_NATIONAL"],
};
const REQUIRED = ["roll_no", "name", "dob", "gender", "program_code", "admission_date", "seat_type", "social_category", "nationality"];

export function precheck(rows: Record<string, string>[], headers: string[]) {
  const missingCols = REQUIRED.filter((h) => !headers.includes(h));
  const seen = new Map<string, number>();
  const problems = rows.map((r, i) => {
    const p: string[] = [];
    REQUIRED.forEach((f) => { if (headers.includes(f) && !r[f]) p.push(`${f} missing`); });
    const a = apaarCheck(r.apaar_id ?? ""); if (a) p.push(a);
    ["dob", "admission_date"].forEach((f) => { if (r[f] && !/^\d{4}-\d{2}-\d{2}$|^\d{2}[-/.]\d{2}[-/.]\d{4}$/.test(r[f])) p.push(`${f} not a date`); });
    Object.entries(ENUMS).forEach(([f, vals]) => {
      const v = (r[f] ?? "").toUpperCase();
      if (v && !vals.includes(v)) p.push(/[;,/|+&]/.test(v) ? `${f}: more than one value` : `${f} '${r[f]}' unknown`);
    });
    if (r.roll_no) { if (seen.has(r.roll_no)) p.push(`roll ${r.roll_no} repeats row ${seen.get(r.roll_no)}`); else seen.set(r.roll_no, i + 1); }
    return p;
  });
  return { missingCols, problems };
}
