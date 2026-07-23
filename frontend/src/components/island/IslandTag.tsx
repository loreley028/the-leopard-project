import type { ReactNode } from "react";
import { Tag } from "animal-island-ui";

export function IslandTag({ children }: { children: ReactNode }) {
  return <Tag className="island-tag" color="app-green" size="small" variant="soft">{children}</Tag>;
}
