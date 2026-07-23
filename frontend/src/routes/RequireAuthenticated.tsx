import { Navigate } from "react-router-dom";
import { useAuth } from "../features/auth/AuthContext";

export function RequireAuthenticated({ children }: { children: React.ReactNode }) {
  const { principal, loading } = useAuth();
  if (loading) return <p role="status">正在确认登录状态…</p>;
  return principal ? children : <Navigate to="/login" replace />;
}
