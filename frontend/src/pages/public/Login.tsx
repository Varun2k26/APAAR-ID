import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { homeFor, ROLE_LABEL, useAuth } from "../../lib/auth";
import { ErrorText, useAsync } from "../../components/ui";
import PublicShell from "../../components/PublicShell";

export default function Login() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const demo = useAsync(() => api.get("/api/v1/dev/demo-accounts").catch(() => null), []);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(u = username, p = password) {
    setBusy(true); setErr(null);
    try {
      const r = await api.post("/api/v1/auth/login", { username: u, password: p });
      if (r.mfa_required) { setMfaToken(r.mfa_token); setUsername(u); setCode(""); }
      else { signIn(r.access_token, r.user); nav(homeFor(r.user.role)); }
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  async function submitMfa() {
    setBusy(true); setErr(null);
    try {
      const r = await api.post("/api/v1/auth/mfa", { mfa_token: mfaToken, code });
      signIn(r.access_token, r.user); nav(homeFor(r.user.role));
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  const hint = demo.data?.accounts?.find((a: any) => a.username === username)?.totp_now;

  return (
    <PublicShell right={<Link to="/verify" className="text-white underline-offset-2 hover:underline">Verify a credential</Link>}>
      <div className="grid gap-8 lg:grid-cols-[400px_1fr]">
        <div>
          <h1 className="text-[22px] font-semibold">Sign in</h1>
          {!mfaToken ? (
            <form className="panel mt-4 space-y-4 p-5" onSubmit={(e) => { e.preventDefault(); submit(); }}>
              <div><label className="label" htmlFor="u">Username</label>
                <input id="u" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></div>
              <div><label className="label" htmlFor="p">Password</label>
                <input id="p" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></div>
              <ErrorText error={err} />
              <button className="btn-primary w-full" disabled={busy || !username || !password}>Sign in</button>
            </form>
          ) : (
            <form className="panel mt-4 space-y-4 p-5" onSubmit={(e) => { e.preventDefault(); submitMfa(); }}>
              <div>
                <div className="text-sm font-medium">2-step verification</div>
                <p className="mt-1 text-sm text-ink-500">Enter the 6-digit code from the authenticator app registered to <span className="font-medium text-ink-800">{username}</span>.</p>
              </div>
              <input className="input mono h-11 text-center text-lg tracking-[0.5em]" inputMode="numeric" maxLength={6} value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus aria-label="Verification code" />
              {hint && <p className="help">Demo environment: the current code is <button type="button" className="link mono" onClick={() => setCode(hint)}>{hint}</button></p>}
              <ErrorText error={err} />
              <div className="flex gap-2">
                <button type="button" className="btn-secondary" onClick={() => setMfaToken(null)}>Back</button>
                <button className="btn-primary flex-1" disabled={busy || code.length !== 6}>Continue</button>
              </div>
            </form>
          )}
          <div className="panel mt-4 p-5">
            <div className="text-sm font-medium">Students</div>
            <p className="mt-1 text-sm text-ink-500">Sign in with DigiLocker to see your record, share credentials and control access.</p>
            <button className="btn-secondary mt-3 w-full" onClick={() => nav("/mock-digilocker")}>Continue with DigiLocker</button>
          </div>
        </div>

        {demo.data?.accounts?.length > 0 && (
          <div>
            <h2 className="text-[15px] font-semibold">Demo accounts</h2>
            <p className="mt-1 text-sm text-ink-500">This prototype runs on synthetic data. Choose an account to sign in.</p>
            <div className="panel mt-4 overflow-hidden">
              <table className="tbl">
                <thead><tr><th>Role</th><th>Organisation</th><th className="hidden sm:table-cell">Username</th><th /></tr></thead>
                <tbody>{demo.data.accounts.map((a: any) => (
                  <tr key={a.username}>
                    <td className="font-medium">{ROLE_LABEL[a.role]}</td>
                    <td className="text-ink-600">{a.org ?? a.display_name}</td>
                    <td className="mono hidden text-ink-600 sm:table-cell">{a.username}{a.mfa_enabled && <span className="ml-2 font-sans text-xs text-ink-500">2-step</span>}</td>
                    <td className="text-right"><button className="btn-secondary btn-sm" disabled={busy} onClick={() => submit(a.username, a.password)}>Sign in</button></td>
                  </tr>))}</tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </PublicShell>
  );
}
