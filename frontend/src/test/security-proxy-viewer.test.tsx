import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SecurityProxyCard } from "../pages/SectorDetailPage";
import { normalizeViewerObservation } from "../api/client";
import type { ViewerObservation } from "../types";

const history = Array.from({ length: 5 }, (_, index) => ({ trading_date: `2026-08-${String(index + 3).padStart(2, "0")}`, close: 10 + index }));
const trend = { recent_closes: history, ma5: 12, ma10: null, ma20: null, distance_to_ma5_pct: 2, distance_to_ma10_pct: null, distance_to_ma20_pct: null };

const cpo: ViewerObservation = {
  market_path_key: "cpo", viewer_source_mode: "security_proxy", fallback_reason: "provider_failed",
  disclosure: "代理证券用于观察主题相关标的表现，不代表官方板块指数或完整行业表现。",
  security_proxy: { display_label: "代理观察", status: "available", recommended_display_mode: "etf_plus_three_leaders", cache_hit: false, quote_datetime: "2026-08-04T14:30:00+08:00", instruments: [
    { symbol: "sh515880", security_name: "通信ETF", proxy_role: "etf", coverage_type: "partial", current: .636, pre_close: .582, change: .054, pct_change: 9.28, quote_datetime: "2026-08-04T14:30:00+08:00", quote_status: "available", error_class: null, ...trend },
    ...["中际旭创", "新易盛", "天孚通信"].map((security_name, index) => ({ symbol: `sz300${308 + index}`, security_name, proxy_role: "leader" as const, coverage_type: "leader_representative", current: 1, pre_close: 1, change: 0, pct_change: 1, quote_datetime: "2026-08-04T14:30:00+08:00", quote_status: "available" as const, error_class: null, ...trend })),
  ] },
};

describe("SecurityProxyCard", () => {
  it("shows CPO as ETF plus three independent leaders without aggregate board return", () => {
    render(<SecurityProxyCard observation={cpo} />);
    expect(screen.getAllByText("代理观察")).toHaveLength(1);
    expect(screen.getByText("部分覆盖")).toBeInTheDocument();
    expect(screen.getAllByText(/^核心公司 ·/)).toHaveLength(3);
    expect(screen.getByText(/不代表官方板块指数/)).toBeInTheDocument();
    expect(screen.getAllByText("近5日走势")).toHaveLength(4);
    expect(screen.getAllByText("MA5")).toHaveLength(4);
    expect(screen.queryByText("板块涨跌")).not.toBeInTheDocument();
  });

  it("shows unavailable security without zero substitution and explicit no-proxy state", () => {
    const unavailable: ViewerObservation = { ...cpo, security_proxy: { ...cpo.security_proxy!, instruments: [{ ...cpo.security_proxy!.instruments[0], current: null, pct_change: null, quote_status: "unavailable" }] } };
    render(<SecurityProxyCard observation={unavailable} />);
    expect(screen.getByText("行情暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
    render(<SecurityProxyCard observation={{ ...cpo, viewer_source_mode: "unavailable", security_proxy: null, fallback_reason: "no_reliable_security_proxy" }} />);
    expect(screen.getByText("暂无可靠的代理证券行情")).toBeInTheDocument();
  });

  it("renders innovative medicine as one ETF and three independent stocks", () => {
    const innovativeMedicine: ViewerObservation = {
      ...cpo,
      market_path_key: "innovative_drug_medicine",
      security_proxy: {
        ...cpo.security_proxy!,
        instruments: [
          { ...cpo.security_proxy!.instruments[0], symbol: "sz159992", security_name: "创新药ETF", proxy_role: "etf" },
          { ...cpo.security_proxy!.instruments[1], symbol: "sh600276", security_name: "恒瑞医药" },
          { ...cpo.security_proxy!.instruments[2], symbol: "sh603259", security_name: "药明康德" },
          { ...cpo.security_proxy!.instruments[3], symbol: "sz300760", security_name: "迈瑞医疗" },
        ],
      },
    };
    render(<SecurityProxyCard observation={innovativeMedicine} />);
    for (const name of ["创新药ETF", "恒瑞医药", "药明康德", "迈瑞医疗"]) expect(document.body).toHaveTextContent(name);
    expect(screen.queryByText("板块涨跌")).not.toBeInTheDocument();
  });

  it("renders four CPO instruments from real numeric-string API values without a synthetic return", () => {
    const numericStringCpo = normalizeViewerObservation({
      ...cpo,
      security_proxy: {
        ...cpo.security_proxy!,
        instruments: cpo.security_proxy!.instruments.map((item, index) => ({
          ...item,
          current: ["0.632", "914.43", "410.50", "207.44"][index],
          pre_close: ["0.642", "947.74", "424.30", "216.85"][index],
          change: ["-0.010", "-33.31", "-13.80", "-9.41"][index],
          pct_change: ["-1.56", "-3.51", "-3.25", "-4.34"][index],
        })),
      },
    });
    render(<SecurityProxyCard observation={numericStringCpo} />);
    expect(screen.getByText("0.632")).toBeInTheDocument();
    expect(screen.getByText("-1.56%")).toBeInTheDocument();
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
    expect(screen.queryByText("板块涨跌")).not.toBeInTheDocument();
  });

  it("keeps a malformed individual quote visible without fabricated values or a page failure", () => {
    const malformed = normalizeViewerObservation({
      ...cpo,
      security_proxy: {
        ...cpo.security_proxy!,
        instruments: cpo.security_proxy!.instruments.map((item, index) => index === 0 ? { ...item, current: "", pre_close: "bad", change: Infinity, pct_change: "NaN", quote_datetime: undefined } : item),
      },
    });
    render(<SecurityProxyCard observation={malformed} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(3);
    expect(screen.getAllByText(/^核心公司 ·/)).toHaveLength(3);
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
  });
});
