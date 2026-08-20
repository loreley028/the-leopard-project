import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BroadMarketOverview, MarketCoreProxyObservation, MarketCoreShanghaiReader } from "../components/market/MarketCoreReader";
import type { MarketCoreBroadMarket, MarketCoreHistoryRow, MarketCoreProxyGroup, MarketCoreShanghai } from "../types";

const history: MarketCoreHistoryRow[] = Array.from({ length: 20 }, (_, index) => ({
  trading_date: `2026-07-${String(index + 1).padStart(2, "0")}`,
  close: 3900 + index,
  pct_change: index ? 0.1 : null,
  quote_datetime: `2026-07-${String(index + 1).padStart(2, "0")}T15:00:00+08:00`,
  captured_at: null,
  source: "sina_public_daily_http",
  data_mode: "completed_eod",
}));

const staleShanghai: MarketCoreShanghai = {
  market_core: "standalone_objective", symbol: "sh000001", name: "上证指数",
  date_axis_kind: "market_trading_day",
  live: { status: "unavailable", current: null, pre_close: null, pct_change: null, quote_datetime: null, server_received_at: null, freshness: "stale", provider: "tencent_standard_security_quote", error_code: "stale_quote" },
  latest_completed: history.at(-1)!, history,
  coverage: { available_days: 20, first_date: history[0].trading_date, latest_date: history.at(-1)!.trading_date, missing_dates: [] },
  indicators: { ma5: 3917, ma10: 3914.5, ma20: 3909.5, distance_to_ma5_pct: null, distance_to_ma10_pct: null, distance_to_ma20_pct: null },
};

const proxyGroups: MarketCoreProxyGroup[] = [{
  proxy_set: "cpo", display_name: "CPO", status: "available",
  instruments: ["通信ETF", "中际旭创", "新易盛", "天孚通信"].map((name, index) => ({
    symbol: ["sh515880", "sz300308", "sz300502", "sz300394"][index], security_code: ["515880.SH", "300308.SZ", "300502.SZ", "300394.SZ"][index], name, role: index === 0 ? "etf" : "leader", coverage_type: index === 0 ? "partial" : "full",
    live: { ...staleShanghai.live, status: "available", current: 10 + index, pre_close: 9 + index, pct_change: 1, quote_datetime: "2026-08-14T14:30:00+08:00", freshness: "fresh" },
    latest_completed: history.at(-1)!, history,
    coverage: staleShanghai.coverage,
    indicators: staleShanghai.indicators,
  })),
}];

describe("Market Core reader surfaces", () => {
  it("keeps same-day lunch quotes visible and labels them as the latest session quote", () => {
    const lunchShanghai: MarketCoreShanghai = {
      ...staleShanghai,
      live: { ...staleShanghai.live, status: "available", current: 3926.96, pre_close: 3910, pct_change: .43, quote_datetime: "2026-08-18T11:30:00+08:00", freshness: "session_latest", display_mode: "same_day_session_latest", session_state: "lunch_break", error_code: null },
    };
    const broad: MarketCoreBroadMarket = {
      market_core: "standalone_objective", date_axis_kind: "market_trading_day", trading_date_axis: history.slice(-10).map(item => item.trading_date),
      universe: "broad_market_anchors", provider: "tencent_standard_security_quote", provider_role: "diagnostic_provider", cache_hit: false, provider_request_count: 1,
      anchors: proxyGroups[0].instruments.map(item => ({ ...item, live: { ...item.live, freshness: "session_latest", display_mode: "same_day_session_latest", session_state: "lunch_break" } })),
    };
    render(<><MarketCoreShanghaiReader market={lunchShanghai} /><BroadMarketOverview shanghai={lunchShanghai} broad={broad} /></>);
    expect(screen.getByText("当日最新行情")).toBeVisible();
    expect(screen.getByText(/当前为非连续交易时段，已显示当日最新行情/)).toBeVisible();
    expect(screen.getAllByText(/当日最新行情 · 行情时间/)).toHaveLength(4);
    expect(screen.getByText("3,926.96")).toBeVisible();
    expect(screen.queryByText("当前实时行情已结束")).not.toBeInTheDocument();
  });

  it("keeps provider quote seconds visible rather than substituting a client timestamp", () => {
    const current = { ...staleShanghai, live: { ...staleShanghai.live, status: "available" as const, current: 3926.96, pre_close: 3910, pct_change: .43, quote_datetime: "2026-08-18T13:11:35+08:00", freshness: "fresh" as const, display_mode: "live" as const, session_state: "afternoon_trading" as const, error_code: null } };
    render(<MarketCoreShanghaiReader market={current} includeHistory={false} />);
    expect(screen.getByText(/2026-08-18.*13:11:35/)).toBeVisible();
  });

  it("keeps completed history and all moving averages visible after a stale live quote", () => {
    render(<MarketCoreShanghaiReader market={staleShanghai} />);
    expect(screen.getByText(/当前实时行情已结束/)).toBeVisible();
    expect(screen.getAllByText("3,917.00").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("最近10个完整交易日上证行情")).toBeVisible();
    expect(screen.getAllByText("2026-07-20")).toHaveLength(2);
    expect(screen.queryByText("历史不足")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("sina_public_daily_http");
    expect(document.body).not.toHaveTextContent("tencent_standard_security_quote");
  });

  it("renders fixed proxy securities independently without a synthetic theme return", () => {
    render(<MarketCoreProxyObservation groups={proxyGroups} disclosure="代理证券用于观察相关标的表现，不代表官方板块指数或完整行业表现。" />);
    expect(screen.getAllByText("代理ETF")).toHaveLength(1);
    expect(screen.getAllByText("核心公司")).toHaveLength(3);
    for (const name of ["通信ETF", "中际旭创", "新易盛", "天孚通信"]) expect(screen.getByText(name)).toBeVisible();
    expect(screen.getAllByText("最近10个完整交易日")).toHaveLength(4);
    expect(document.body).not.toHaveTextContent("板块涨跌");
    expect(document.body).not.toHaveTextContent("平均收益");
    expect(document.body).not.toHaveTextContent("加权收益");
  });

  it("uses A-share tones for Shanghai prices and renders broad completed days newest first", () => {
    const current = { ...staleShanghai, live: { ...staleShanghai.live, status: "available" as const, current: 3926.96, pre_close: 3910, pct_change: .43, quote_datetime: "2026-08-18T14:30:00+08:00", freshness: "fresh" as const, display_mode: "live" as const, session_state: "afternoon_trading" as const, error_code: null } };
    const broad: MarketCoreBroadMarket = {
      market_core: "standalone_objective", date_axis_kind: "market_trading_day", trading_date_axis: history.slice(-10).map(item => item.trading_date),
      universe: "broad_market_anchors", provider: "tencent_standard_security_quote", provider_role: "diagnostic_provider", cache_hit: false, provider_request_count: 1,
      anchors: proxyGroups[0].instruments.map(item => ({ ...item, live: { ...item.live, freshness: "fresh", display_mode: "live", session_state: "afternoon_trading" } })),
    };
    render(<><MarketCoreShanghaiReader market={current} includeHistory={false} /><BroadMarketOverview shanghai={current} broad={broad} /></>);
    expect(screen.getByText("3,926.96")).toHaveClass("a-share-positive");
    const rows = Array.from(document.querySelectorAll(".aligned-broad-market-row:not(.aligned-broad-market-header)"));
    expect(rows[0]).toHaveTextContent("07-20");
    expect(rows.at(-1)).toHaveTextContent("07-11");
  });
});
