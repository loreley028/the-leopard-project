import { Link, useLocation } from "../../routes/router";
const items = [["/", "最新报告"], ["/sectors", "板块研究"], ["/reports", "报告库"]] as const;
export function IslandNav() {
  const { pathname } = useLocation();
  const active = (to: string) => to === "/" ? pathname === "/" : to === "/reports" ? pathname === "/reports" : pathname === to || pathname.startsWith(`${to}/`);
  return <nav className="island-nav" aria-label="主导航">{items.map(([to, label]) => <Link key={to} to={to} className={active(to) ? "active" : undefined} aria-current={active(to) ? "page" : undefined}>{label}</Link>)}</nav>;
}
