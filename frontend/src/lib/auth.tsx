import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";

export type User = {
  id: number;
  username: string;
  display_name: string;
  role: "AICTE_ADMIN" | "INSTITUTION_ADMIN" | "DATA_OPERATOR" | "UNIVERSITY_REGISTRAR" | "REGULATOR" | "STUDENT";
  institution: { id: number; name: string; code: string; state: string } | null;
  university: { id: number; name: string } | null;
  regulator_body: string | null;
  person_id: number | null;
  mfa_enabled: boolean;
  permissions: string[];
};

type Ctx = { user: User | null; loading: boolean; signIn: (token: string, u: User) => void; signOut: () => void;
             refresh: () => Promise<void> };
const AuthCtx = createContext<Ctx>(null as unknown as Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    if (!getToken()) { setUser(null); setLoading(false); return; }
    try { setUser(await api.get<User>("/api/v1/auth/me")); } catch { setUser(null); }
    setLoading(false);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const signIn = (token: string, u: User) => { setToken(token); setUser(u); };
  const signOut = () => { setToken(null); setUser(null); };
  return <AuthCtx.Provider value={{ user, loading, signIn, signOut, refresh }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export function homeFor(role?: string) {
  switch (role) {
    case "AICTE_ADMIN": return "/aicte";
    case "INSTITUTION_ADMIN":
    case "DATA_OPERATOR": return "/institution";
    case "STUDENT": return "/student";
    case "REGULATOR": return "/regulator";
    case "UNIVERSITY_REGISTRAR": return "/university";
    default: return "/login";
  }
}

export const ROLE_LABEL: Record<string, string> = {
  AICTE_ADMIN: "AICTE administrator", INSTITUTION_ADMIN: "Institution administrator", DATA_OPERATOR: "Data entry operator",
  UNIVERSITY_REGISTRAR: "University registrar", REGULATOR: "Regulator", STUDENT: "Student",
};
