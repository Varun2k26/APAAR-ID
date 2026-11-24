import { useEffect, useState } from "react";
import { Check, CircleAlert, X } from "lucide-react";
import { Link } from "react-router-dom";
import { verifyPresentation, type Result } from "../../lib/verify";
import { api } from "../../lib/api";
import { DL, humanize, Loading } from "../../components/ui";
import PublicShell from "../../components/PublicShell";

const LABEL: Record<string, string> = {
  name: "Name", apaar_id: "APAAR ID", dob: "Date of birth", gender: "Gender", institution: "Institution", program: "Programme",
  level: "Level", admission_year: "Admission year", year_of_study: "Year of study", roll_no: "Roll number",
  enrollment_status: "Enrolment status", social_category: "Category", degree: "Degree", university: "University",
  class_awarded: "Class awarded", cgpa: "CGPA", year_of_award: "Year of award", specialisation: "Specialisation",
};
const TYPE_LABEL: Record<string, string> = { EnrollmentCredential: "Enrolment credential", DegreeCredential: "Degree credential" };

export default function Verify() {
  const [input, setInput] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState<any>(null);

  async function run(vp: string) {
    setBusy(true); setRes(null); setOnline(null);
    try { setRes(await verifyPresentation(vp)); }
    catch (e: any) { setRes({ valid: false, steps: [], claims: {}, offline: false, reason: e.message }); }
    setBusy(false);
  }
  useEffect(() => {
    const m = window.location.hash.match(/vp=([^&]+)/);
    if (m) { const vp = decodeURIComponent(m[1]); setInput(vp); run(vp); }
  }, []);

  const kind = res ? TYPE_LABEL[(res.type ?? []).slice(-1)[0] ?? ""] ?? "Credential" : "";
  return (
    <PublicShell right={<Link to="/login" className="text-white underline-offset-2 hover:underline">Sign in</Link>}>
      <div className="mx-auto max-w-3xl">
        <h1 className="text-[22px] font-semibold">Verify a credential</h1>
        <p className="mt-1 text-sm text-ink-500">Checks the issuer's signature, accreditation and revocation status. The check runs on this device and nothing is sent to a server.</p>

        {res && (
          <div className="panel mt-6 overflow-hidden">
            <div className={`flex items-start gap-3 border-b px-5 py-4 ${res.valid ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
              <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white ${res.valid ? "bg-emerald-700" : "bg-red-700"}`}>
                {res.valid ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}</span>
              <div className="min-w-0">
                <div className={`text-[17px] font-semibold ${res.valid ? "text-emerald-900" : "text-red-900"}`}>{res.valid ? `Valid ${kind.toLowerCase()}` : "This credential is not valid"}</div>
                <div className="text-sm text-ink-700">{res.valid ? `Issued by ${res.issuer?.name}` : res.reason}</div>
              </div>
              {res.offline && <span className="ml-auto shrink-0 text-xs text-ink-600">Checked offline with cached data</span>}
            </div>
            <div className="grid gap-6 p-5 md:grid-cols-[1fr_1.2fr]">
              <div>
                <h2 className="mb-2 text-[13px] font-semibold text-ink-700">Checks</h2>
                <ul className="space-y-2.5">
                  {res.steps.map((s, i) => (
                    <li key={i} className="flex gap-2.5 text-sm">
                      {s.ok === true ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" /> : s.ok === false ? <X className="mt-0.5 h-4 w-4 shrink-0 text-red-700" /> : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />}
                      <div><div className="text-ink-900">{s.label}</div>{s.detail && <div className="text-xs text-ink-500">{s.detail}</div>}</div>
                    </li>))}
                </ul>
                {res.rootFingerprint && <p className="mt-4 text-xs text-ink-500">Root key fingerprint <span className="mono">{res.rootFingerprint}</span></p>}
              </div>
              {Object.keys(res.claims).length > 0 && (
                <div>
                  <h2 className="mb-1 text-[13px] font-semibold text-ink-700">Shared by the holder</h2>
                  <DL rows={Object.entries(res.claims).map(([k, v]) => [LABEL[k] ?? k, k === "enrollment_status" ? humanize(String(v)) : String(v ?? "—")])} />
                  {(res.hiddenCount ?? 0) > 0 && <p className="mt-2 text-xs text-ink-500">{res.hiddenCount} other field(s) in this credential were not shared.</p>}
                </div>
              )}
            </div>
            {res.valid && (
              <div className="flex flex-wrap items-center gap-3 border-t border-ink-200 bg-ink-50 px-5 py-3 text-[13px] text-ink-600">
                <span>Need a record of this check for your files?</span>
                <button className="btn-secondary btn-sm" onClick={async () => setOnline(await api.post("/api/v1/verify", { presentation: input, verifier: "Public verifier page" }))}>Verify with the registry</button>
                {online && <span className={online.valid ? "text-emerald-800" : "text-red-800"}>{online.valid ? "Confirmed by the registry. The holder can see this check." : online.reason}</span>}
              </div>)}
          </div>
        )}
        {busy && <Loading label="Verifying…" />}

        <div className="panel mt-6 p-5">
          <label className="label" htmlFor="vp">Credential</label>
          <textarea id="vp" className="input mono h-24 text-xs" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Paste the credential, or open the link from its QR code" />
          <button className="btn-primary mt-3" onClick={() => run(input)} disabled={!input || busy}>Verify</button>
        </div>
      </div>
    </PublicShell>
  );
}
