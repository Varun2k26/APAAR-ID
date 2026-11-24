import { useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, openBlob } from "../../lib/api";
import { disclosureNames, present } from "../../lib/verify";
import { Empty, humanize, Loading, Modal, PageHeader, Panel, Status, useAsync, useToast, when } from "../../components/ui";

const LABEL: Record<string, string> = {
  name: "Name", apaar_id: "APAAR ID", dob: "Date of birth", gender: "Gender", institution: "Institution", program: "Programme", level: "Level",
  admission_year: "Admission year", year_of_study: "Year of study", roll_no: "Roll number", enrollment_status: "Enrolment status",
  social_category: "Social category", degree: "Degree", university: "University", class_awarded: "Class awarded", cgpa: "CGPA",
  year_of_award: "Year of award", specialisation: "Specialisation",
};

export default function Wallet() {
  const creds = useAsync(() => api.get("/api/v1/me/credentials"), []);
  const me = useAsync(() => api.get("/api/v1/me/record"), []);
  const { toast, node } = useToast();
  const active = (me.data?.enrollments ?? []).filter((e: any) => e.enrollment_status === "ACTIVE");
  const hasValid = (eid: number) => (creds.data ?? []).some((c: any) => c.enrollment_id === eid && !c.revoked && c.type === "ENROLLMENT");
  const missing = active.filter((e: any) => !hasValid(e.enrollment_id));
  return (
    <div className="space-y-6">
      {node}
      <PageHeader title="Credentials" description="Digitally signed proof of your enrolment and degrees. Choose what to share; anyone can check it with the QR code, even offline." />
      {missing.map((e: any) => (
        <Panel key={e.enrollment_id}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><div className="font-medium">Enrolment credential</div><div className="text-sm text-ink-600">{e.institution} · {e.program}</div></div>
            <button className="btn-primary" onClick={async () => { try { await api.post("/api/v1/me/credentials", { enrollment_id: e.enrollment_id }); toast("Credential issued"); creds.reload(); } catch (x: any) { toast(x.message, "bad"); } }}>Request credential</button>
          </div>
        </Panel>))}
      {creds.loading ? <Loading /> : !creds.data?.length ? (missing.length ? null : <Panel><Empty>You have no credentials yet.</Empty></Panel>)
        : creds.data.map((c: any) => <CredentialCard key={c.id} c={c} toast={toast} />)}
    </div>
  );
}

function CredentialCard({ c, toast }: { c: any; toast: (m: string, t?: any) => void }) {
  const names = useMemo(() => disclosureNames(c.sd_jwt), [c.sd_jwt]);
  const [reveal, setReveal] = useState<string[]>(c.default_reveal.filter((n: string) => names.includes(n)));
  const vp = useMemo(() => present(c.sd_jwt, reveal), [c.sd_jwt, reveal]);
  const url = `${window.location.origin}/verify#vp=${vp}`;
  const [big, setBig] = useState(false);
  const title = c.type === "DEGREE" ? `${c.claims.degree}${c.claims.specialisation ? ` in ${c.claims.specialisation}` : ""}` : `Enrolment · ${c.claims.program}`;
  return (
    <Panel title={title} description={`${c.type === "DEGREE" ? c.claims.university : c.claims.institution} · issued ${when(c.issued_at)}`}
      actions={<>{c.revoked ? <Status s="REVOKED" /> : <Status s="VALID" label="Valid" />}
        {c.type === "DEGREE" && <button className="btn-secondary btn-sm" onClick={() => openBlob(`/api/v1/credentials/${c.id}/certificate.pdf`)}>Certificate (PDF)</button>}</>}>
      {c.revoked && <p className="mb-4 text-sm text-red-800">Revoked: {c.revocation_reason}. Verifiers will see this credential as not valid.</p>}
      <div className="grid gap-6 md:grid-cols-[1fr_auto]">
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink-700">Information to share</h3>
          <div className="divide-y divide-ink-100 rounded border border-ink-200">
            {names.map((n) => {
              const on = reveal.includes(n);
              return (
                <label key={n} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-ink-50">
                  <input type="checkbox" checked={on} onChange={() => setReveal(on ? reveal.filter((x) => x !== n) : [...reveal, n])} />
                  <span className="w-40 shrink-0 text-ink-600">{LABEL[n] ?? n}{c.sensitive.includes(n) && <span className="ml-1 text-xs text-amber-800">(sensitive)</span>}</span>
                  <span className={`min-w-0 truncate ${on ? "text-ink-900" : "text-ink-400"}`}>{on ? (n === "enrollment_status" ? humanize(String(c.claims[n])) : String(c.claims[n] ?? "—")) : "Not shared"}</span>
                </label>);
            })}
          </div>
        </div>
        <div className="flex flex-col items-center gap-2">
          <button className="rounded border border-ink-200 bg-white p-2 hover:border-ink-400" onClick={() => setBig(true)} title="Enlarge">
            <QRCodeSVG value={url} size={184} level="L" /></button>
          <span className="text-xs text-ink-500">{reveal.length} of {names.length} items shared</span>
          <div className="flex gap-2">
            <button className="btn-secondary btn-sm" onClick={() => { navigator.clipboard?.writeText(url); toast("Link copied"); }}>Copy link</button>
            <a className="btn-secondary btn-sm" href={url} target="_blank" rel="noreferrer">Open</a>
          </div>
        </div>
      </div>
      <Modal open={big} onClose={() => setBig(false)} title="Scan to verify" wide>
        <div className="flex flex-col items-center gap-3 py-2"><QRCodeSVG value={url} size={Math.min(520, window.innerWidth - 96)} level="L" />
          <p className="text-[13px] text-ink-500">Shares: {reveal.map((n) => LABEL[n] ?? n).join(", ") || "nothing"}</p></div>
      </Modal>
    </Panel>
  );
}
