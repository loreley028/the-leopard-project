import type { ReactNode } from "react";
export function IslandEmptyState({ title, children }: { title: string; children: ReactNode }) { return <div className="empty-state" role="status"><span aria-hidden="true">⌁</span><h2>{title}</h2><p>{children}</p></div>; }
