import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../lib/api";
import { BRAND } from "../../lib/brand";
import { useAuth } from "../../lib/auth";
import { ErrorText, Loading, useAsync } from "../../components/ui";

/** SIMULATED DigiLocker authorisation screen (OAuth 2.0 authorisation-code flow). */
export default function DigiLocker() {
  const nav = useNavigate();
  const demo = useAsync(() => api.get("/api/v1/dev/demo-accounts").catch(() => null), []);
  const [apaar, setApaar] = useState("");
  const [otp, setOtp] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const state = useMemo(() => Math.random().toString(36).slice(2), []);

  async function allow() {
    setErr(null);
    try { nav((await api.post("/api/v1/mock/digilocker/authorize", { apaar_id: apaar, otp, state })).redirect); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="min-h-screen bg-[#f2f4f8]">
      <div className="bg-amber-100 py-1.5 text-center text-xs font-medium text-amber-900">Simulated DigiLocker for the prototype. This is not the real service.</div>
      <div className="mx-auto max-w-[420px] px-4 py-10">
        <div className="panel overflow-hidden">
          <div className="bg-[#1d4aa3] px-5 py-3 font-semibold text-white">DigiLocker</div>
          <div className="space-y-4 p-5">
            <p className="text-sm text-ink-700"><span className="font-semibold">{BRAND}</span> is requesting your APAAR ID to sign you in.</p>
            <div><label className="label" htmlFor="apaar">APAAR ID</label>
              <input id="apaar" className="input mono" placeholder="0000 0000 0000" value={apaar} onChange={(e) => setApaar(e.target.value)} /></div>
            <div><label className="label" htmlFor="otp">One-time password</label>
              <input id="otp" className="input mono" inputMode="numeric" value={otp} onChange={(e) => setOtp(e.target.value)} />
              <p className="help">Sent to your Aadhaar-linked mobile. In this simulation the OTP is {demo.data?.digilocker_otp ?? "123456"}.</p></div>
            <ErrorText error={err} />
            <div className="flex gap-2"><button className="btn-secondary flex-1" onClick={() => nav("/login")}>Deny</button>
              <button className="btn flex-1 border-[#1d4aa3] bg-[#1d4aa3] text-white hover:bg-[#173b84]" disabled={!apaar || !otp} onClick={allow}>Allow</button></div>
          </div>
        </div>
        {demo.data?.students?.length > 0 && (
          <div className="panel mt-4">
            <div className="border-b border-ink-200 px-4 py-2.5 text-[13px] font-semibold">Demo students</div>
            {demo.data.students.map((s: any) => (
              <button key={s.apaar_id} onClick={() => { setApaar(s.apaar_id); setOtp(demo.data.digilocker_otp); }}
                className="block w-full border-b border-ink-100 px-4 py-2.5 text-left last:border-0 hover:bg-ink-50">
                <div className="flex justify-between gap-2 text-sm"><span className="font-medium">{s.name}</span><span className="mono text-ink-500">{s.apaar_id}</span></div>
                <div className="text-xs text-ink-500">{s.note}</div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function DigiLockerCallback() {
  const [params] = useSearchParams();
  const { signIn } = useAuth();
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.post("/api/v1/auth/digilocker/token", { code: params.get("code") })
      .then((r) => { signIn(r.access_token, r.user); nav("/student"); })
      .catch((e) => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="mx-auto max-w-md p-10">
      {err ? <><ErrorText error={err} /><button className="btn-secondary mt-3" onClick={() => nav("/login")}>Back to sign in</button></> : <Loading label="Signing you in…" />}
    </div>
  );
}
