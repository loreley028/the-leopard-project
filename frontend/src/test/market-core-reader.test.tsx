import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketCoreProxyObservation, MarketCoreShanghaiReader } from "../components/market/MarketCoreReader";
import type { MarketCoreHistoryRow, MarketCoreProxyGroup, MarketCoreShanghai } from "../types";

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
});
