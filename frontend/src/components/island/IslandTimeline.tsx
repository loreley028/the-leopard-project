import type { ReactNode } from "react";
export function IslandTimeline({ items }: { items: Array<{ date: string; title: string; content: ReactNode }> }) { return <ol className="timeline">{items.map((item, index) => <li key={`${item.date}-${index}`}><time>{item.date}</time><strong>{item.title}</strong><div>{item.content}</div></li>)}</ol>; }
