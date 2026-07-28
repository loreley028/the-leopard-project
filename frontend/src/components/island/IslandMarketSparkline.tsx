import type { MarketSnapshot } from "../../types";

export function IslandMarketSparkline({ history }: { history: MarketSnapshot[] }) {
  if (history.length < 2) return <p className="muted">暂无足够行情绘制趋势图。</p>;
  const values = history.flatMap(item => [item.close, item.ma5, item.ma20]).filter((value): value is number => value != null);
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
  const points = (field: "close" | "ma5" | "ma20") => history.map((item, index) => `${(index / (history.length - 1)) * 100},${38 - ((((item[field] ?? item.close) - min) / span) * 34)}`).join(" ");
  const maxVolume = Math.max(...history.map(item => item.volume ?? 0), 1);
  return <div className="market-sparkline" aria-label="近20个交易日收盘价、均线与成交量趋势">
    <svg viewBox="0 0 100 50" role="img"><title>近20个交易日行情趋势</title>{history.map((item, index) => <rect key={item.trade_date} x={(index / history.length) * 100} y={40 + (1 - ((item.volume ?? 0) / maxVolume)) * 9} width={Math.max(1, 80 / history.length)} height={((item.volume ?? 0) / maxVolume) * 9} fill="#cbd5e1" />)}<polyline points={points("close")} fill="none" stroke="#111827" strokeWidth="1.2" /><polyline points={points("ma5")} fill="none" stroke="#dc2626" strokeWidth=".8" /><polyline points={points("ma20")} fill="none" stroke="#2563eb" strokeWidth=".8" /></svg>
    <small>黑：收盘 · 红：MA5 · 蓝：MA20 · 灰柱：成交量</small>
  </div>;
}
