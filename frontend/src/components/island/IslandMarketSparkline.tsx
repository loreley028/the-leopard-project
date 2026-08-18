import type { MarketSnapshot, PrimaryMarketHistoryRow } from "../../types";

type CompletedHistoryPoint = MarketSnapshot | PrimaryMarketHistoryRow;
const tradingDate = (item: CompletedHistoryPoint) => "trading_date" in item ? item.trading_date : item.trade_date;
const chartValue = (item: CompletedHistoryPoint, field: "close" | "ma5" | "ma20") => {
  if (field === "close" || "trading_date" in item) return item.close;
  return item[field] ?? item.close;
};

export function IslandMarketSparkline({ history }: { history: CompletedHistoryPoint[] }) {
  if (history.length < 2) return <p className="muted">暂无足够行情绘制趋势图。</p>;
  const values = history.flatMap(item => [item.close, "ma5" in item ? item.ma5 : null, "ma20" in item ? item.ma20 : null]).filter((value): value is number => value != null);
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
  const points = (field: "close" | "ma5" | "ma20") => history.map((item, index) => {
    const value = chartValue(item, field);
    return `${(index / (history.length - 1)) * 100},${38 - (((value - min) / span) * 34)}`;
  }).join(" ");
  const maxVolume = Math.max(...history.map(item => "volume" in item ? item.volume ?? 0 : 0), 1);
  return <div className="market-sparkline" aria-label="近20个交易日收盘价、均线与成交量趋势">
    <svg viewBox="0 0 100 50" role="img"><title>完整交易日收盘趋势</title>{history.map((item, index) => { const volume = "volume" in item ? item.volume ?? 0 : 0; return <rect key={tradingDate(item)} x={(index / history.length) * 100} y={40 + (1 - (volume / maxVolume)) * 9} width={Math.max(1, 80 / history.length)} height={(volume / maxVolume) * 9} fill="#cbd5e1" />; })}<polyline points={points("close")} fill="none" stroke="#111827" strokeWidth="1.2" /><polyline points={points("ma5")} fill="none" stroke="#dc2626" strokeWidth=".8" /><polyline points={points("ma20")} fill="none" stroke="#2563eb" strokeWidth=".8" /></svg>
    <small>黑：收盘 · 红：MA5 · 蓝：MA20；均线不足时仅显示收盘。</small>
  </div>;
}
