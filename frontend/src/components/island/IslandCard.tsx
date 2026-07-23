import type { ReactNode } from "react";
import { Card } from "animal-island-ui";

export function IslandCard({ children, title }: { children: ReactNode; title?: string }) {
  return <Card className="island-card" color="default">{title && <h2>{title}</h2>}{children}</Card>;
}
