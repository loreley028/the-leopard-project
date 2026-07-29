import { describe, expect, it } from "vitest";
import type { Sector } from "../types";
import { compareSectors } from "../utils/sector-order";

const sector = (overrides: Partial<Sector>): Sector => ({
  sector_key: "base", sector_name: "基础", group_name: "第一组", group_order: 1, overall_order: 1,
  latest_view: null, mentioned_in_latest_published: false, market_support_status: "supported",
  data_status: "supported", market_status_detail: "研究辅助", current_path_status: "not_mentioned",
  current_path_status_label: "未提", latest_market: null, recent_mention_count: 0,
  ...overrides,
});

describe("stable sector ordering", () => {
  it("always keeps catalog group order ahead of heat", () => {
    const hotLaterGroup = sector({ sector_key: "hot", group_order: 2, overall_order: 3, is_pinned_for_research: true, mentioned_in_latest_published: true });
    const quietFirstGroup = sector({ sector_key: "quiet", group_order: 1, overall_order: 2 });
    expect([hotLaterGroup, quietFirstGroup].sort(compareSectors).map(item => item.sector_key)).toEqual(["quiet", "hot"]);
  });

  it("uses pinned, current mention, holding and catalog order deterministically", () => {
    const rows = [
      sector({ sector_key: "catalog", overall_order: 1 }),
      sector({ sector_key: "holding", overall_order: 4, strict_holding_interval: { status: "active" } }),
      sector({ sector_key: "mentioned", overall_order: 3, mentioned_in_latest_published: true }),
      sector({ sector_key: "pinned", overall_order: 5, is_pinned_for_research: true }),
    ];
    expect(rows.sort(compareSectors).map(item => item.sector_key)).toEqual(["pinned", "mentioned", "holding", "catalog"]);
    const first = [...rows].sort(compareSectors).map(item => item.sector_key);
    expect([...rows].reverse().sort(compareSectors).map(item => item.sector_key)).toEqual(first);
  });

  it("does not use EOD or intraday price changes", () => {
    const a = sector({ sector_key: "a", overall_order: 1, intraday_snapshot: { sector_key: "a", trade_date: "2026-07-28", observed_at: "14:20", index_value: 120, pre_close: 100, pct_change: 20, volume: null, amount: null, provider: "research", provider_role: "research_provider", data_status: "intraday_fresh", fetched_at: "2026-07-28T06:20:00Z" } });
    const b = sector({ sector_key: "b", overall_order: 2 });
    expect([b, a].sort(compareSectors).map(item => item.sector_key)).toEqual(["a", "b"]);
  });
});
