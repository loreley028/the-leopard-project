import { describe, expect, it } from "vitest";
import type { IntradayStatus, Sector } from "../types";
import { intradayDataLabel, intradaySystemLabel, realtimePresentation } from "../utils/intraday";

const status = (changes: Partial<IntradayStatus> = {}): IntradayStatus => ({
  session_status: "paused", market_phase: "intraday_open", market_phase_detail: "intraday_open",
  intraday_trade_date: "2026-07-28",
  refresh_interval_minutes: 5, provider: "synthetic", provider_role: "diagnostic_provider",
  production_primary: null, research_notice: "test", last_refresh_at: null, next_refresh_at: null,
  latest_snapshot_at: null, success_count: 0, failure_count: 0, stale_count: 0,
  unsupported_count: 1, viewer_provider_access: false, auto_start: false, ...changes,
});

const sector = (changes: Partial<Sector> = {}) => ({
  sector_key: "semiconductor", sector_name: "半导体", group_name: "科技", group_order: 1, overall_order: 1,
  latest_view: null, mentioned_in_latest_published: true, market_support_status: "supported", data_status: "supported",
  market_status_detail: "", current_path_status: "hold", current_path_status_label: "持有", latest_market: null,
  ...changes,
} as Sector);

describe("central intraday labels", () => {
  it("does not call an open-session provider failure a market closure", () => {
    expect(intradaySystemLabel(status({ failure_count: 65 }))).toBe("盘中行情获取失败");
    expect(intradayDataLabel("provider_failed", status({ failure_count: 65 }))).toBe("获取失败");
  });
  it("distinguishes break, after-close and non-trading closure", () => {
    expect(intradaySystemLabel(status({ market_phase: "market_break", market_phase_detail: "market_break" }))).toBe("午间休市");
    expect(intradaySystemLabel(status({ market_phase: "market_closed", market_phase_detail: "after_close" }))).toBe("已收盘");
    expect(intradaySystemLabel(status({ market_phase: "market_closed", market_phase_detail: "non_trading_day" }))).toBe("休市");
    expect(intradaySystemLabel(status({ market_phase: "calendar_error", market_phase_detail: "calendar_out_of_range", market_session: "calendar_error", calendar_status: "calendar_out_of_range" }))).toBe("交易日历待更新");
    expect(intradayDataLabel("calendar_error", status({ market_phase: "calendar_error", market_session: "calendar_error" }))).toBe("交易日历待更新");
  });
  it("marks delayed cached data without inventing a value", () => {
    expect(intradaySystemLabel(status({ stale_count: 2, latest_snapshot_at: "2026-07-27T02:00:00Z" }))).toBe("盘中数据延迟");
    expect(intradayDataLabel("intraday_stale", status())).toBe("数据延迟");
  });
});

describe("realtime market presentation", () => {
  it("shows only the current-day fresh percentage and HH:MM", () => {
    const result = realtimePresentation(sector({ intraday_status: "intraday_fresh", intraday_snapshot: {
      sector_key: "semiconductor", trade_date: "2026-07-28", observed_at: "07/28 14:20", index_value: 100,
      pre_close: 99, pct_change: 1.26, volume: null, amount: null, provider: "eastmoney_board_spot",
      provider_role: "research_provider", data_status: "intraday_fresh", fetched_at: "2026-07-28T06:20:00Z",
    } }), status());
    expect(result).toEqual({ value: "+1.26%", detail: "14:20", tone: "up" });
  });
  it("never falls back to an EOD percentage after a Provider failure", () => {
    const failed = sector({ intraday_status: "provider_failed", latest_market: { trade_date: "2026-07-27", daily_pct_change: 9.99 } as Sector["latest_market"] });
    expect(realtimePresentation(failed, status())).toEqual({ value: "暂无实时", tone: "flat" });
  });
  it("handles lunch, after-close completion and non-trading days", () => {
    const fresh = sector({ intraday_status: "market_break", intraday_snapshot: { trade_date: "2026-07-28", pct_change: .83 } as Sector["intraday_snapshot"] });
    expect(realtimePresentation(fresh, status({ market_phase: "market_break", market_phase_detail: "market_break" }))).toMatchObject({ value: "+0.83%", detail: "午间休市" });
    const closed = sector({ latest_market: { trade_date: "2026-07-28", daily_pct_change: -2.14 } as Sector["latest_market"] });
    expect(realtimePresentation(closed, status({ market_phase: "market_closed", market_phase_detail: "after_close" }))).toEqual({ value: "-2.14%", detail: "今日收盘", tone: "down" });
    expect(realtimePresentation(closed, status({ market_phase: "market_closed", market_phase_detail: "non_trading_day" }))).toEqual({ value: "休市", tone: "flat" });
  });
});
