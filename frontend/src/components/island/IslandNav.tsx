import { NavLink } from "react-router-dom";
import { useAuth } from "../../features/auth/AuthContext";
const items = [["/", "最新报告"], ["/reports", "历史报告"], ["/sectors", "板块观点"], ["/admin", "管理区"]] as const;
export function IslandNav() { const { principal } = useAuth(); return <nav className="island-nav" aria-label="主导航">{items.filter(([to]) => to !== "/admin" || principal?.role === "admin").map(([to, label]) => <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>)}</nav>; }
