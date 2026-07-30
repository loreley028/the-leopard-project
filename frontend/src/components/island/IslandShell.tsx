import type { ReactNode } from "react";
import { Link } from "../../routes/router";
import { IslandHeader } from "./IslandHeader";
import { IslandNav } from "./IslandNav";
import "./island.css";

export function IslandShell({ children }: { children: ReactNode }) {
  return <div className="island-shell"><IslandHeader /><IslandNav /><main id="main-content" className="island-main">{children}</main><footer><span>研究型 Web MVP · PDF 是主线，行情仅作辅助</span><Link to="/about">第三方组件与许可说明</Link></footer></div>;
}
