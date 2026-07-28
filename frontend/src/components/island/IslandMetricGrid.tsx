import type { MarketSnapshot } from "../../types";
import { formatNumber, formatPct } from "../../utils/format";

export function IslandMetricGrid({ market }: { market: MarketSnapshot | null }) {
  if (!market) return <p className="muted">行情辅助数据未附加</p>;
  const metrics = [
    ["当日涨跌", formatPct(market.daily_pct_change)],
    ["近5日", formatPct(market.return_5d)],
    ["近10日", formatPct(market.return_10d)],
    ["近20日", formatPct(market.return_20d)],
    ["MA5", formatNumber(market.ma5)],
    ["MA10", formatNumber(market.ma10)],
    ["MA20", formatNumber(market.ma20)],
    ["量比5日", formatNumber(market.volume_ratio_5d)],
    ["量比20日", formatNumber(market.volume_ratio_20d)],
  ];
  return <dl className="metric-grid">{metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}
