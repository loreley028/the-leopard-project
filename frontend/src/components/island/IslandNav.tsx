import { Link, useLocation } from "../../routes/router";
import { useAuth } from "../../features/auth/AuthContext";
const items = [["/", "最新报告"], ["/sectors", "板块研究"], ["/reports", "报告库"], ["/admin", "管理区"]] as const;
export function IslandNav() {
  const { principal } = useAuth();
  const { pathname } = useLocation();
  const active = (to: string) => to === "/" ? pathname === "/" : to === "/reports" ? pathname === "/reports" : pathname === to || pathname.startsWith(`${to}/`);
  return <nav className="island-nav" aria-label="主导航">{items.filter(([to]) => to !== "/admin" || principal?.role === "admin").map(([to, label]) => <Link key={to} to={to} className={active(to) ? "active" : undefined} aria-current={active(to) ? "page" : undefined}>{label}</Link>)}</nav>;
}
