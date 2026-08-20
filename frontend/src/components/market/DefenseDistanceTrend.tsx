import type { DefenseLineTrendPoint } from "../../types";
import { formatPct } from "../../utils/format";

const chartWidth = 720;
const chartHeight = 220;
const chartPadding = { top: 20, right: 18, bottom: 34, left: 48 };

const shortDate = (value: string) => `${Number(value.slice(5, 7))}/${Number(value.slice(8, 10))}`;
const point = (value: number | null) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type ValidTrendPoint = DefenseLineTrendPoint & {
  distance_pct: number;
  distance_points: number;
  defense_line_value: number;
  index_close: number;
  source_report_date: string;
};
type PlottedPoint = { item: ValidTrendPoint; index: number; x: number; y: number };

export function DefenseDistanceTrend({ points }: { points: DefenseLineTrendPoint[] }) {
  const chartPoints = points.filter((item): item is ValidTrendPoint => (
    item.available && item.distance_pct != null && item.distance_points != null && item.defense_line_value != null && item.index_close != null && item.source_report_date != null
  ));
  const values = chartPoints.map(item => item.distance_pct);
  const extreme = Math.max(1, ...values.map(value => Math.abs(value))) * 1.15;
  const innerWidth = chartWidth - chartPadding.left - chartPadding.right;
  const innerHeight = chartHeight - chartPadding.top - chartPadding.bottom;
  const xAt = (index: number) => chartPadding.left + (points.length < 2 ? innerWidth / 2 : index / (points.length - 1) * innerWidth);
  const yAt = (value: number) => chartPadding.top + (extreme - value) / (extreme * 2) * innerHeight;
  const plotted: PlottedPoint[] = chartPoints.map(item => ({ item, index: points.indexOf(item), x: xAt(points.indexOf(item)), y: yAt(item.distance_pct) }));
  const segments = plotted.slice(1).flatMap((item, index) => item.index === plotted[index].index + 1 ? [[plotted[index], item] as const] : []);
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), Math.max(0, points.length - 1)])];
  const titleFor = (item: DefenseLineTrendPoint) => [
    `交易日：${item.trading_date}`,
    `攻防线来源：${item.source_report_date ? `来自 ${item.source_report_date} 报告` : "无有效攻防线"}`,
    `攻防线：${point(item.defense_line_value)}`,
    `上证收盘：${point(item.index_close)}`,
    `距攻防线：${point(item.distance_points)} / ${formatPct(item.distance_pct)}`,
    `收盘位置：${item.close_position === "close_above_defense_line" ? "在线上" : item.close_position === "close_below_defense_line" ? "在线下" : "附近 / 等于攻防线"}`,
  ].join("\n");

  return <section className="defense-distance-trend" aria-labelledby="defense-distance-trend-title">
    <div className="defense-distance-trend-heading"><div><p className="eyebrow">近30个交易日攻防距离趋势</p><p id="defense-distance-trend-title">以完整交易日上证收盘相对同日有效攻防线的百分比距离展示；缺少有效攻防线的日期留空。</p></div><span>百分比</span></div>
    {points.length === 0 ? <p className="defense-validation-empty">暂无完整交易日数据。</p> : <figure className="defense-distance-chart" data-testid="defense-distance-chart">
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label="近30个交易日攻防距离趋势图">
        <line className="defense-distance-zero" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={yAt(0)} y2={yAt(0)} />
        <text className="defense-distance-axis-label" x={4} y={chartPadding.top + 5}>{formatPct(extreme)}</text>
        <text className="defense-distance-axis-label" x={4} y={yAt(0) - 4}>0.00%</text>
        <text className="defense-distance-axis-label" x={4} y={chartHeight - chartPadding.bottom + 5}>{formatPct(-extreme)}</text>
        {segments.map(([from, to]) => <line className={to.item.distance_pct >= 0 ? "defense-distance-positive" : "defense-distance-negative"} key={`${from.item.trading_date}-${to.item.trading_date}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} />)}
        {plotted.map(({ item, x, y }) => <circle className={item.distance_pct >= 0 ? "defense-distance-point-positive" : "defense-distance-point-negative"} cx={x} cy={y} r="4.5" key={item.trading_date}><title>{titleFor(item)}</title></circle>)}
        {labelIndexes.map(index => points[index] ? <text className="defense-distance-date" key={points[index].trading_date} x={xAt(index)} y={chartHeight - 8} textAnchor="middle">{shortDate(points[index].trading_date)}</text> : null)}
      </svg>
      <figcaption>上方为正（红），下方为负（绿）。悬停数据点可查看交易日、报告来源、攻防线、收盘、点数差与百分比差。</figcaption>
    </figure>}
  </section>;
}
