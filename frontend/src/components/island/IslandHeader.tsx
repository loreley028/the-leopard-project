import { Link } from "../../routes/router";

export function IslandHeader() {
  return <header className="island-header"><div className="island-brand"><div className="brand-mark" aria-hidden="true">LP</div><div><strong>The Leopard Project</strong><span>岛屿研究手册</span></div></div><Link className="admin-entry" to="/admin/login">Admin</Link></header>;
}
