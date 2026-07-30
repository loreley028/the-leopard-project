import { Navigate } from "./router";
import { useAuth } from "../features/auth/AuthContext";
export function RequireAdmin({ children }: { children: React.ReactNode }) { const { principal, loading } = useAuth(); if (loading) return <p role="status">正在确认权限…</p>; return principal?.role === "admin" ? children : <Navigate to="/login" replace />; }
