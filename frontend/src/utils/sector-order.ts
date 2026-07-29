import type { Sector } from "../types";

const STATUS_RANK: Record<string, number> = {
  turn_hold: 0, hold: 1, strong_watch: 2, watch: 3, weak_watch: 4,
  turn_weak: 5, exit: 6, avoid: 7, not_mentioned: 8,
};

const activeHolding = (item: Sector) => Number(
  item.strict_holding_interval?.status === "active" || item.broad_holding_interval?.status === "active",
);

export type StableSectorSort = "research" | "status" | "date" | "catalog";

export function compareSectors(a: Sector, b: Sector, sort: StableSectorSort = "research"): number {
  const group = a.group_order - b.group_order;
  if (group) return group;
  if (sort === "catalog") return a.overall_order - b.overall_order;
  if (sort === "status") {
    return (STATUS_RANK[a.current_path_status] ?? 99) - (STATUS_RANK[b.current_path_status] ?? 99)
      || (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "")
      || a.overall_order - b.overall_order;
  }
  if (sort === "date") {
    return (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "")
      || a.overall_order - b.overall_order;
  }
  return Number(Boolean(b.is_pinned_for_research)) - Number(Boolean(a.is_pinned_for_research))
    || Number(b.mentioned_in_latest_published) - Number(a.mentioned_in_latest_published)
    || activeHolding(b) - activeHolding(a)
    || (STATUS_RANK[a.effective_status ?? a.current_path_status] ?? 99) - (STATUS_RANK[b.effective_status ?? b.current_path_status] ?? 99)
    || (b.recent_mention_count ?? 0) - (a.recent_mention_count ?? 0)
    || (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "")
    || a.overall_order - b.overall_order;
}
