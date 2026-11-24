// Thin client over the public API. The web app uses exactly the API an ERP would.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  try { return localStorage.getItem("spine.token"); } catch { return null; }
}
export function setToken(t: string | null) {
  try { t ? localStorage.setItem("spine.token", t) : localStorage.removeItem("spine.token"); } catch { /* private mode */ }
}

async function request<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* not json */ }
    if (res.status === 401 && token && !path.includes("/auth/")) {
      setToken(null);
      window.location.href = "/login";
    }
    throw new ApiError(res.status, msg);
  }
  if (raw) return res as unknown as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  upload: <T = any>(p: string, f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return request<T>("POST", p, fd);
  },
  blob: async (p: string) => {
    const res = await request<Response>("GET", p, undefined, true);
    return res.blob();
  },
};

export async function download(path: string, filename: string) {
  const b = await api.blob(path);
  const url = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function openBlob(path: string) {
  const b = await api.blob(path);
  window.open(URL.createObjectURL(b), "_blank");
}
