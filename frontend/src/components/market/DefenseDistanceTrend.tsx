import { useState } from "react";
import type { DefenseLineTrendPoint, IntradayDefenseOverlay } from "../../types";
import { formatPct } from "../../utils/format";

const chartWidth = 720;
const chartHeight = 240;
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
type ChartPoint = ValidTrendPoint & { provisional?: boolean };
type HoveredBar = { item: ChartPoint; left: number; top: number };

export function DefenseDistanceTrend({ points, intradayOverlay }: { points: DefenseLineTrendPoint[]; intradayOverlay?: IntradayDefenseOverlay | null }) {
  const [hovered, setHovered] = useState<HoveredBar | null>(null);
  const completed = points.filter((item): item is ValidTrendPoint => (
    item.available && item.distance_pct != null && item.distance_points != null && item.defense_line_value != null && item.index_close != null && item.source_report_date != null
  ));
  const provisional: ChartPoint | null = intradayOverlay ? {
    available: true, trading_date: intradayOverlay.trading_date, source_report_id: intradayOverlay.source_report_id,
    source_report_date: intradayOverlay.source_report_date, defense_line_value: intradayOverlay.defense_line_value,
    index_name: intradayOverlay.index_name, index_close: intradayOverlay.index_current,
    distance_points: intradayOverlay.distance_points, distance_pct: intradayOverlay.distance_pct,
    close_position: intradayOverlay.close_position, data_mode: "completed_eod", provisional: true,
  } : null;
  const chartPoints: ChartPoint[] = provisional ? [...completed, provisional] : completed;
  const values = chartPoints.map(item => item.distance_points);
  const extreme = Math.max(10, ...values.map(value => Math.abs(value))) * 1.15;
  const innerWidth = chartWidth - chartPadding.left - chartPadding.right;
  const innerHeight = chartHeight - chartPadding.top - chartPadding.bottom;
  const axisCount = points.length + (provisional ? 1 : 0);
  const xAt = (index: number) => chartPadding.left + (axisCount < 2 ? innerWidth / 2 : index / (axisCount - 1) * innerWidth);
  const zeroY = chartPadding.top + innerHeight / 2;
  const yAt = (value: number) => chartPadding.top + (extreme - value) / (extreme * 2) * innerHeight;
  const barWidth = Math.min(14, Math.max(7, innerWidth / Math.max(axisCount, 1) * .62));
  const labelIndexes = [...new Set([0, Math.floor((axisCount - 1) / 2), Math.max(0, axisCount - 1)])];
  const closePosition = (item: DefenseLineTrendPoint) => item.close_position === "close_above_defense_line" ? "攻防线上方" : item.close_position === "close_below_defense_line" ? "攻防线下方" : "攻防线附近";
  const showTooltip = (item: ChartPoint, target: SVGRectElement) => {
    const bounds = target.ownerSVGElement?.parentElement?.getBoundingClientRect();
    if (!bounds) return;
    const rect = target.getBoundingClientRect();
    const tooltipWidth = Math.min(260, bounds.width - 16);
    const targetCenter = rect.left - bounds.left + rect.width / 2;
    const desired = targetCenter + 12 + tooltipWidth > bounds.width ? targetCenter - tooltipWidth - 12 : targetCenter + 12;
    setHovered({ item, left: Math.max(8, Math.min(bounds.width - tooltipWidth - 8, desired)), top: Math.max(12, rect.top - bounds.top + rect.height / 2) });
  };

  return <section className="defense-distance-trend" aria-labelledby="defense-distance-trend-title">
    <div className="defense-distance-trend-heading"><div><p className="eyebrow">近30个交易日攻防距离趋势</p><p id="defense-distance-trend-title">以完整交易日上证收盘相对同日有效攻防线的点数差展示；线上为红，线下为绿；缺少有效攻防线的日期留空。今日盘中仅作临时观察。</p></div><span>点数</span></div>
    {points.length === 0 ? <p className="defense-validation-empty">暂无完整交易日数据。</p> : <figure className="defense-distance-chart" data-testid="defense-distance-chart">
      <div className="defense-distance-chart-canvas"><svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label="近30个交易日攻防距离点数柱状图">
        <line className="defense-distance-zero" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={zeroY} y2={zeroY} />
        <text className="defense-distance-axis-label" x={2} y={chartPadding.top + 5}>+{Math.round(extreme)}</text>
        <text className="defense-distance-axis-label" x={21} y={zeroY - 4}>0</text>
        <text className="defense-distance-axis-label" x={2} y={chartHeight - chartPadding.bottom + 5}>-{Math.round(extreme)}</text>
        {chartPoints.map(item => {
          const index = item.provisional ? points.length : points.indexOf(item);
          const y = yAt(item.distance_points);
          const top = Math.min(y, zeroY);
          const height = Math.max(1, Math.abs(zeroY - y));
          const tone = item.distance_points > 0 ? "positive" : item.distance_points < 0 ? "negative" : "neutral";
          return <rect aria-describedby={hovered?.item.trading_date === item.trading_date ? "defense-distance-tooltip" : undefined} aria-label={`${item.trading_date}${item.provisional ? "盘中临时" : ""}，${point(item.distance_points)}点，${closePosition(item)}`} className={`defense-distance-bar defense-distance-bar-${tone}${item.provisional ? " defense-distance-bar-intraday" : ""}`} data-testid={`defense-distance-bar-${item.trading_date}${item.provisional ? "-intraday" : ""}`} height={height} key={`${item.trading_date}-${item.provisional ? "intraday" : "completed"}`} onFocus={event => showTooltip(item, event.currentTarget)} onMouseEnter={event => showTooltip(item, event.currentTarget)} onMouseLeave={() => setHovered(null)} onBlur={() => setHovered(null)} rx="2" tabIndex={0} width={barWidth} x={xAt(index) - barWidth / 2} y={top} />;
        })}
        {labelIndexes.map(index => { const item: DefenseLineTrendPoint | ChartPoint | null = index === points.length && provisional ? provisional : points[index] ?? null; return item ? <text className="defense-distance-date" key={`${item.trading_date}-${index}`} x={xAt(index)} y={chartHeight - 8} textAnchor="middle">{shortDate(item.trading_date)}{item === provisional ? " 盘中" : ""}</text> : null; })}
      </svg>{hovered && <aside className="defense-distance-tooltip" id="defense-distance-tooltip" role="tooltip" style={{ left: hovered.left, top: hovered.top }}><strong>{hovered.item.trading_date}{hovered.item.provisional ? " · 今日盘中" : ""}</strong><span>攻防线来源：{hovered.item.source_report_date} 报告</span><span>攻防线：{point(hovered.item.defense_line_value)}</span><span>{hovered.item.provisional ? "上证当前" : "上证收盘"}：{point(hovered.item.index_close)}</span><span>距攻防线：{point(hovered.item.distance_points)} 点</span><span>百分比差：{formatPct(hovered.item.distance_pct)}</span><span>{hovered.item.provisional ? "当前位置" : "收盘位置"}：{closePosition(hovered.item)}</span></aside>}</div>
      <figcaption>红柱表示攻防线上方，绿柱表示攻防线下方；半透明柱为今日盘中临时观察。悬停或聚焦柱体可查看完整证据。</figcaption>
    </figure>}
  </section>;
}
