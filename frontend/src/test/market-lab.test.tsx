import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../features/auth/AuthContext";
import { MemoryRouter } from "../routes/router";

const shanghai = {
  market_core: "standalone_objective", symbol: "sh000001", name: "上证指数",
  live: { status: "available", current: 3965.44, pre_close: 3946.68, pct_change: 0.48, quote_datetime: "2026-08-13T13:43:00+08:00", server_received_at: "2026-08-13T13:43:01+08:00", freshness: "fresh", provider: "tencent_standard_security_quote", error_code: null },
  latest_completed: { trading_date: "2026-08-12", close: 3946.68, pct_change: 0.32, quote_datetime: "2026-08-12T15:20:00+08:00", captured_at: "2026-08-12T15:20:01+08:00", source: "tencent_standard_security_quote", data_mode: "completed_eod" },
  history: [{ trading_date: "2026-08-12", close: 3946.68, pct_change: 0.32, quote_datetime: "2026-08-12T15:20:00+08:00", captured_at: "2026-08-12T15:20:01+08:00", source: "tencent_standard_security_quote", data_mode: "completed_eod" }],
  coverage: { available_days: 1, first_date: "2026-08-12", latest_date: "2026-08-12", missing_dates: [] },
  indicators: { ma5: null, ma10: null, ma20: null, distance_to_ma5_pct: null, distance_to_ma10_pct: null, distance_to_ma20_pct: null },
};

const proxies = {
  market_core: "standalone_objective", proxy_set: "all", provider: "tencent_standard_security_quote", provider_role: "diagnostic_provider", cache_hit: false, provider_request_count: 2,
  groups: [{ proxy_set: "cpo", display_name: "CPO", status: "available", instruments: ["sh515880", "sz300308", "sz300502", "sz300394"].map((symbol, index) => ({
    symbol, name: ["通信ETF", "中际旭创", "新易盛", "天孚通信"][index], role: index ? "leader" : "etf", coverage_type: index ? "full" : "partial",
    live: { status: "available", current: 10 + index, pre_close: 9 + index, pct_change: 1.1, quote_datetime: "2026-08-13T13:43:00+08:00", server_received_at: "2026-08-13T13:43:01+08:00", freshness: "fresh", provider: "tencent_standard_security_quote", error_code: null },
    latest_completed: { trading_date: "2026-08-12", close: 9 + index, pct_change: 0.2, quote_datetime: "2026-08-12T15:20:00+08:00", captured_at: "2026-08-12T15:20:01+08:00", source: "tencent_standard_security_quote", data_mode: "completed_eod" },
    history: [{ trading_date: "2026-08-12", close: 9 + index, pct_change: null, quote_datetime: "2026-08-12T15:20:00+08:00", captured_at: "2026-08-12T15:20:01+08:00", source: "tencent_standard_security_quote", data_mode: "completed_eod" }],
    coverage: { available_days: 1, first_date: "2026-08-12", latest_date: "2026-08-12", missing_dates: [] },
    indicators: { ma5: null, ma10: null, ma20: null, distance_to_ma5_pct: null, distance_to_ma10_pct: null, distance_to_ma20_pct: null },
  })) }],
};

afterEach(() => vi.unstubAllGlobals());

describe("Market Lab", () => {
  it("renders zero-report market facts, CPO values, dates, coverage, and honest insufficient history", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input); calls.push(url);
      return Promise.resolve(new Response(JSON.stringify(url.includes("/market/shanghai") ? shanghai : proxies), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    render(<MemoryRouter initialEntries={["/market-lab"]}><AuthProvider initialPrincipal={null}><App /></AuthProvider></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Market Lab" })).toBeVisible();
    expect(screen.getByText("上证指数")).toBeVisible();
    expect(screen.getByText("3,965.44")).toBeVisible();
    const group = screen.getByRole("heading", { name: "CPO" }).parentElement!;
    expect(within(group).getByText("通信ETF")).toBeVisible();
    expect(within(group).getByText("中际旭创")).toBeVisible();
    expect(within(group).getByText("新易盛")).toBeVisible();
    expect(within(group).getByText("天孚通信")).toBeVisible();
    expect(screen.getAllByText(/真实完成日：1/).length).toBeGreaterThan(1);
    expect(screen.getAllByText("历史不足").length).toBeGreaterThan(3);
    expect(screen.getAllByText("2026-08-12").length).toBeGreaterThan(1);
    expect(calls).toEqual(["/api/v1/market/shanghai", "/api/v1/market/proxies/all"]);
    expect(calls.join(" ")).not.toContain("report");
  });

  it("keeps completed moving averages visible when the live quote is unavailable", async () => {
    const unavailable = {
      ...shanghai,
      live: { ...shanghai.live, status: "unavailable", current: null, pct_change: null, quote_datetime: null, freshness: "unavailable", error_code: "stale_quote" },
      coverage: { available_days: 20, first_date: "2026-07-17", latest_date: "2026-08-13", missing_dates: [] },
      indicators: { ma5: 3942.87, ma10: 3895.74, ma20: 3862.24, distance_to_ma5_pct: null, distance_to_ma10_pct: null, distance_to_ma20_pct: null },
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(new Response(JSON.stringify(String(input).includes("/market/shanghai") ? unavailable : proxies), { status: 200, headers: { "Content-Type": "application/json" } }))));
    render(<MemoryRouter initialEntries={["/market-lab"]}><AuthProvider initialPrincipal={null}><App /></AuthProvider></MemoryRouter>);
    expect(await screen.findByText("3,942.87")).toBeVisible();
    expect(screen.getAllByText("实时行情暂不可用").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("历史不足").length).toBeGreaterThan(0);
  });
});
