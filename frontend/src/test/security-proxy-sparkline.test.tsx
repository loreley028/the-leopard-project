import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizeViewerObservation } from "../api/client";
import { SecurityProxySparkline } from "../components/island/SecurityProxySparkline";

const closes = (values: number[]) => values.map((close, index) => ({ trading_date: `2026-08-${String(index + 3).padStart(2, "0")}`, close }));

describe("SecurityProxySparkline", () => {
  it("handles empty, one-point, two-point, and identical-price histories safely", () => {
    const { rerender } = render(<SecurityProxySparkline closes={[]} />);
    expect(screen.getByText("近5日：暂无足够历史")).toBeInTheDocument();
    rerender(<SecurityProxySparkline closes={closes([10])} />);
    expect(screen.getByRole("img", { name: "近五个交易日收盘价走势" }).querySelectorAll("circle")).toHaveLength(1);
    rerender(<SecurityProxySparkline closes={closes([10, 11])} />);
    expect(screen.getByRole("img").querySelector("polyline")?.getAttribute("points")).toContain("0,");
    rerender(<SecurityProxySparkline closes={closes([10, 10, 10, 10, 10])} />);
    expect(screen.getByRole("img").querySelector("polyline")?.getAttribute("points")).not.toContain("NaN");
  });

  it("normalizes numeric strings, rejects invalid closes, and retains only five sorted days", () => {
    const observation = normalizeViewerObservation({
      market_path_key: "cpo", viewer_source_mode: "security_proxy", fallback_reason: "provider_failed", disclosure: null,
      security_proxy: { display_label: "代理观察", status: "available", recommended_display_mode: "etf", cache_hit: false, quote_datetime: null, instruments: [{
        symbol: "sh515880", security_name: "通信ETF", proxy_role: "etf", coverage_type: "partial", current: "10", pre_close: null, change: null, pct_change: null, quote_datetime: null, quote_status: "available", error_class: null,
        recent_closes: [{ trading_date: "2026-08-06", close: "11" }, { trading_date: "bad", close: "12" }, { trading_date: "2026-08-05", close: "NaN" }, ...closes([1, 2, 3, 4, 5, 6])], ma5: "4", ma10: null, ma20: null, distance_to_ma5_pct: "50", distance_to_ma10_pct: null, distance_to_ma20_pct: null,
      }] },
    });
    const instrument = observation.security_proxy!.instruments[0];
    expect(instrument.recent_closes).toHaveLength(5);
    expect(instrument.recent_closes.every(item => Number.isFinite(item.close))).toBe(true);
    expect(instrument.ma5).toBe(4);
  });
});
