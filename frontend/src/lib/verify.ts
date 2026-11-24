// In-browser SD-JWT verifier. Nothing about the presentation is sent anywhere:
// the trust list and status list are public files (cached for offline use), the check is local.
import * as ed from "@noble/ed25519";
import { sha256 } from "@noble/hashes/sha256";
import { sha512 } from "@noble/hashes/sha512";

ed.etc.sha512Sync = (...m: Uint8Array[]) => sha512(ed.etc.concatBytes(...m));

const enc = new TextEncoder();
const dec = new TextDecoder();

export function b64uToBytes(s: string): Uint8Array {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  const out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
  return out;
}
export function bytesToB64u(b: Uint8Array): string {
  let s = "";
  b.forEach((x) => (s += String.fromCharCode(x)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const json = (s: string) => JSON.parse(dec.decode(b64uToBytes(s)));

function cacheGet(k: string) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } }
function cacheSet(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } }

function verifyJws(token: string, pubB64u: string) {
  const [h, p, s] = token.split(".");
  const ok = ed.verify(b64uToBytes(s), enc.encode(`${h}.${p}`), b64uToBytes(pubB64u));
  if (!ok) throw new Error("signature does not verify");
  return { header: json(h), payload: json(p) };
}

export type Step = { label: string; ok: boolean | null; detail?: string };
export type Result = {
  valid: boolean; steps: Step[]; claims: Record<string, unknown>; issuer?: { id: string; name: string };
  type?: string[]; issuedAt?: number; offline: boolean; rootFingerprint?: string; reason?: string; hiddenCount?: number;
};

async function fetchOrCache(url: string, key: string, asText = false) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    const v = asText ? await r.text() : await r.json();
    cacheSet(key, { v, at: Date.now() });
    return { v, offline: false };
  } catch {
    const c = cacheGet(key);
    if (c) return { v: c.v, offline: true };
    throw new Error(`cannot reach ${url} and nothing cached`);
  }
}

async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  const ds = new DecompressionStream("gzip");
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function verifyPresentation(vp: string): Promise<Result> {
  const steps: Step[] = [];
  let offline = false;
  const fail = (reason: string, extra: Partial<Result> = {}): Result =>
    ({ valid: false, steps, claims: {}, offline, reason, ...extra });
  const [jwt, ...rest] = vp.trim().split("~");
  const discs = rest.filter(Boolean);
  if (!jwt || jwt.split(".").length !== 3) return fail("This is not a recognised credential");

  // 1. AICTE root key (pinned on first use; a change is flagged)
  const root = await fetchOrCache("/api/v1/trust/root", "spine.root");
  offline ||= root.offline;
  const pinned = cacheGet("spine.root.pinned");
  if (!pinned) cacheSet("spine.root.pinned", root.v.jwk.x);
  else if (pinned !== root.v.jwk.x) return fail("The AICTE signing key has changed since this device last verified a credential");

  // 2. Trust list signed by AICTE
  const tl = await fetchOrCache("/api/v1/trust/list", "spine.trustlist");
  offline ||= tl.offline;
  let issuers: any[];
  try { issuers = verifyJws(tl.v.jwt, root.v.jwk.x).payload.issuers; }
  catch { return fail("The issuer register could not be authenticated"); }
  steps.push({ label: "Issuer register is authentic", ok: true, detail: `Signed by AICTE · ${issuers.length} accredited issuers` });

  // 3. Issuer signature
  let header: any, payload: any;
  try { header = json(jwt.split(".")[0]); } catch { return fail("Malformed credential"); }
  const iss = issuers.find((i) => i.kid === header.kid);
  if (!iss) { steps.push({ label: "Issuer is accredited", ok: false }); return fail("Issuer is not on the AICTE trust list"); }
  try { ({ payload } = verifyJws(jwt, iss.jwk.x)); }
  catch { steps.push({ label: "Issuer signature is valid", ok: false }); return fail("The issuer's signature does not match. The credential has been altered or is not genuine"); }
  if (payload.iss !== iss.issuer) return fail("Issuer mismatch");
  steps.push({ label: "Signed by an accredited issuer", ok: true, detail: iss.name });

  // 4. Disclosures
  const sd: string[] = payload.credentialSubject?._sd ?? [];
  const claims: Record<string, unknown> = {};
  for (const d of discs) {
    const digest = bytesToB64u(sha256(enc.encode(d)));
    if (!sd.includes(digest)) {
      steps.push({ label: "Shared information is unaltered", ok: false });
      return fail("Information in this credential has been altered since it was issued");
    }
    const [, name, value] = json(d);
    claims[name] = value;
  }
  steps.push({ label: "Shared information is unaltered", ok: true, detail: `${discs.length} item(s) shared by the holder` });

  // 5. Revocation via Bitstring Status List (whole list fetched: server learns nothing)
  const st = payload.credentialStatus;
  let revoked = false;
  try {
    const path = new URL(st.statusListCredential).pathname;
    const sl = await fetchOrCache(path, `spine.status.${path}`, true);
    offline ||= sl.offline;
    const { payload: slp } = verifyJws(sl.v as string, root.v.jwk.x);
    const enc64 = String(slp.credentialSubject.encodedList).replace(/^u/, "");
    const bits = await gunzip(b64uToBytes(enc64));
    const idx = Number(st.statusListIndex);
    revoked = ((bits[idx >> 3] >> (7 - (idx % 8))) & 1) === 1;
    steps.push({ label: "Not revoked", ok: !revoked, detail: revoked ? "The issuer has revoked this credential"
               : sl.offline ? "Checked against the last downloaded revocation list" : "Checked against the current revocation list" });
  } catch (e) {
    steps.push({ label: "Revocation status unknown", ok: null, detail: "The revocation list could not be loaded" });
  }
  return {
    valid: !revoked, steps, claims, issuer: { id: iss.issuer, name: iss.name }, type: payload.type, issuedAt: payload.iat, offline,
    rootFingerprint: root.v.fingerprint, reason: revoked ? "This credential has been revoked by its issuer" : undefined,
    hiddenCount: Math.max(0, sd.length - discs.length - 1),
  };
}

export function present(sdJwt: string, reveal: string[]): string {
  const [jwt, ...rest] = sdJwt.split("~");
  const keep = rest.filter(Boolean).filter((d) => reveal.includes(json(d)[1]));
  return `${jwt}~${keep.map((d) => d + "~").join("")}`;
}

export function disclosureNames(sdJwt: string): string[] {
  return sdJwt.split("~").slice(1).filter(Boolean).map((d) => json(d)[1]);
}
