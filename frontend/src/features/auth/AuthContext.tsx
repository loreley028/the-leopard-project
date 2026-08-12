import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Principal } from "../../types";

type AuthValue = { principal: Principal | null; loading: boolean; adminLogin: (u: string, p: string) => Promise<void>; logout: () => Promise<void> };
export const AuthContext = createContext<AuthValue>({ principal: null, loading: false, adminLogin: async () => undefined, logout: async () => undefined });
export function AuthProvider({ children, initialPrincipal }: { children: ReactNode; initialPrincipal?: Principal | null }) {
  const [principal, setPrincipal] = useState<Principal | null>(initialPrincipal ?? null);
  const [loading, setLoading] = useState(initialPrincipal === undefined);
  useEffect(() => { if (initialPrincipal !== undefined) return; api.me().then(setPrincipal).catch(() => setPrincipal(null)).finally(() => setLoading(false)); }, [initialPrincipal]);
  return <AuthContext.Provider value={{ principal, loading, adminLogin: async (u, p) => setPrincipal(await api.adminLogin(u, p)), logout: async () => { await api.logout(); setPrincipal(null); } }}>{children}</AuthContext.Provider>;
}
export const useAuth = () => useContext(AuthContext);
