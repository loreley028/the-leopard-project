import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "../routes/router";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandMetricGrid } from "../components/island/IslandMetricGrid";
import { IslandMarketSparkline } from "../components/island/IslandMarketSparkline";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import { MarketCoreProxyObservation } from "../components/market/MarketCoreReader";
import { SecurityProxySparkline } from "../components/island/SecurityProxySparkline";
import type { MarketCoreProxies, SectorResearch, ViewerObservation } from "../types";
import { formatPct, formatSecurityPrice } from "../utils/format";
import { intradayDataLabel } from "../utils/intraday";

const PATH_LABELS: Record<string, string> = { avoid: "不碰", strong_watch: "强观", watch: "观察", weak_watch: "弱观", turn_hold: "转持", hold: "持有", turn_weak: "转弱", exit: "离场", not_mentioned: "未提" };
const aShareTone = (value: number | null | undefined) => value == null || value === 0 ? "a-share-neutral" : value > 0 ? "a-share-positive" : "a-share-negative";
const availablePeriodReturn = (days: NonNullable<SectorResearch["recent_10_trading_days"]>, configured: number | null | undefined) => {
  if (configured != null) return configured;
  if (days.length < 2 || days[0].close <= 0) return null;
  return (days.at(-1)!.close / days[0].close - 1) * 100;
};

export function SectorDetailPage() {
  const { sectorKey = "" } = useParams();
  const [research, setResearch] = useState<SectorResearch | null>();
  const [viewerObservation, setViewerObservation] = useState<ViewerObservation | null>(null);
  const [marketCoreProxies, setMarketCoreProxies] = useState<MarketCoreProxies | null>(null);
  const [pathPeriods, setPathPeriods] = useState(20);
  const [marketDays, setMarketDays] = useState(20);
  useEffect(() => { api.sectorResearch(sectorKey, pathPeriods, marketDays).then(setResearch).catch(() => setResearch(null)); }, [sectorKey, pathPeriods, marketDays]);
  useEffect(() => { api.viewerObservation(sectorKey).then(setViewerObservation).catch(() => setViewerObservation(null)); }, [sectorKey]);
  useEffect(() => {
    if (viewerObservation?.viewer_source_mode !== "security_proxy") { setMarketCoreProxies(null); return; }
    api.marketProxies(sectorKey).then(setMarketCoreProxies).catch(() => setMarketCoreProxies(null));
  }, [sectorKey, viewerObservation?.viewer_source_mode]);
  const monthGroups = useMemo(() => {
    const groups: Array<{ month: string; items: NonNullable<SectorResearch["recent_path"]> }> = [];
    for (const item of [...(research?.recent_path ?? [])].reverse()) {
      const month = item.report_date.slice(0, 7);
      const current = groups.at(-1);
      if (!current || current.month !== month) groups.push({ month, items: [item] }); else current.items.push(item);
    }
    return groups;
  }, [research]);
  if (research === undefined) return <p role="status">加载板块研究档案…</p>;
  if (!research) return <p role="alert">板块研究档案不存在。</p>;
  const intradayLabel = research.intraday_snapshot && research.intraday_status === "intraday_fresh" ? "盘中缓存" : intradayDataLabel(research.intraday_status, research.intraday_session).replace("获取失败", "盘中行情获取失败").replace("数据延迟", "盘中数据延迟");
  const officialBoardAvailable = viewerObservation?.viewer_source_mode === "official_board";
  const recentTradingDays = research.recent_10_trading_days ?? [];
  const tenDayReturn = availablePeriodReturn(recentTradingDays, research.current_latest_market?.return_10d);
  return <div className="page sector-research-detail"><header><p className="eyebrow">{research.group_name}</p><h1>{research.sector_name}</h1><IslandStatusBadge status={research.data_status} /><p>{research.market_status_detail}</p>{research.parent_report_topic === "hotel_catering" && <div className="notice"><strong>上层报告主题：酒店餐饮</strong><p>报告观点保持一条，不复制为两个结论；酒店与餐饮只拆分实时行情研究。</p><p><Link to="/sectors/hotel">酒店行情</Link> · <Link to="/sectors/catering">餐饮行情</Link></p></div>}<div className="path-period-switch" aria-label="直播报告路径期数">{[10,20,40,60].map(value => <button type="button" key={value} className={pathPeriods === value ? "active" : ""} onClick={() => setPathPeriods(value)}>最近{value}期</button>)}</div><p className="muted">路径范围按直播报告期计算；实际显示 {research.recent_path?.length ?? 0} / 可用 {research.available_path_periods ?? 0} 期。无原始PDF的日期只显示冻结路径记录。</p><div className="path-month-groups">{monthGroups.map(group => <section key={group.month}><strong>{group.month}</strong><div className="recent-path-banner">{group.items.map((item, index) => <span key={item.id} className={`path-chip path-${item.path.path_status} ${index === group.items.length - 1 && group === monthGroups.at(-1) ? "latest" : ""}`} title={`${item.report_date} · 报告状态${item.path.path_status_label} · 有效状态${item.effective_status ? PATH_LABELS[item.effective_status] : "暂无"}`}><small>{item.report_date.slice(5)}</small>{item.path.path_status_label.slice(0, 1)}</span>)}</div></section>)}</div></header>
    <div className="dashboard-grid">
      <IslandCard title="报告观点">{research.latest_explicit_view ? <>{research.latest_report_explicitly_mentioned === false && <p className="muted">本期报告（{research.latest_report_date ?? "最新一期"}）未提及；沿用最近明确观点。</p>}<strong>{research.latest_explicit_view.path.path_status_label} · {research.latest_explicit_view.report_date}</strong><p>{research.latest_explicit_view.assessment.current_judgement}</p><p><Link to={`/reports/${research.latest_explicit_view.report_id}`}>查看来源报告</Link></p></> : <p>暂无明确直播观点；“未提”不代表观点失效。</p>}</IslandCard>
      {officialBoardAvailable ? <IslandCard title="当前官方板块行情"><p>状态：<strong>{intradayLabel}</strong></p>{research.intraday_snapshot ? <dl className="intraday-detail-list"><div><dt>当前值</dt><dd>{research.intraday_snapshot.index_value}</dd></div><div><dt>昨收</dt><dd>{research.intraday_snapshot.pre_close}</dd></div><div><dt>实时涨跌</dt><dd>{formatPct(research.intraday_snapshot.pct_change)}</dd></div><div><dt>实时MA5</dt><dd>{research.intraday_snapshot.intraday_ma5 ?? "同源历史不足"}</dd></div><div><dt>相对实时MA5</dt><dd>{formatPct(research.intraday_snapshot.intraday_vs_ma5)}</dd></div><div><dt>最近完整MA5</dt><dd>{research.current_latest_market?.ma5 ?? "—"}</dd></div><div><dt>最近完整MA20</dt><dd>{research.current_latest_market?.ma20 ?? "—"}</dd></div><div><dt>行情时间</dt><dd>{research.intraday_snapshot.observed_at}</dd></div><div><dt>数据状态</dt><dd>{intradayLabel}</dd></div></dl> : <p>保留服务器最近有效缓存；Viewer不会请求Provider。</p>}<p className="reader-provider-note">数据说明：此处为官方板块行情辅助；固定代理证券观察另按独立 Market Core 展示。</p></IslandCard> : <IslandCard title="当前官方板块行情"><p>当前暂无可靠官方板块行情；下方仅提供固定代理证券观察，不替代官方板块指数。</p></IslandCard>}
      {officialBoardAvailable && <IslandCard title={research.current_latest_market?.market_data_mode === "legacy_historical_validation" ? "历史行情" : "最近完整收盘行情"}>{research.market_support_status === "unsupported" ? <p>暂不支持：港股跨市场行情尚未接入，不展示伪造指标。</p> : <><p>{research.current_latest_market?.market_data_mode === "legacy_historical_validation" ? "截至" : "完整交易日："}{research.current_latest_market?.trade_date ?? "未刷新"}</p><IslandMetricGrid market={research.current_latest_market} /></>}</IslandCard>}
    </div>
    {viewerObservation?.viewer_source_mode === "security_proxy" && (marketCoreProxies ? <MarketCoreProxyObservation groups={marketCoreProxies.groups} disclosure={viewerObservation.disclosure} /> : <section className="proxy-observation-panel" aria-label="代理观察面板"><IslandCard title="固定代理证券观察"><p>客观行情辅助加载中；报告观点保持可用。</p></IslandCard></section>)}
    {viewerObservation?.fallback_reason === "no_reliable_security_proxy" && <section className="proxy-observation-panel" aria-label="代理观察面板"><IslandCard title="固定代理证券观察"><p>暂无可靠代理证券行情；报告观点保持可用。</p></IslandCard></section>}
    <IslandCard title="最近10个交易日"><p>10日累计：<strong>{formatPct(tenDayReturn)}</strong>（按完整日收益复合/首尾价格计算，不作百分比简单相加）</p>{recentTradingDays.length > 0 && recentTradingDays.length < 10 && <p className="muted">当前仅有 {recentTradingDays.length} 个完整交易日</p>}<div className="recent-five-detail">{recentTradingDays.length ? recentTradingDays.map(item => <span key={item.trade_date} className={item.daily_pct_change > 0 ? "up" : item.daily_pct_change < 0 ? "down" : "flat"}><time>{item.trade_date}</time><b>{formatPct(item.daily_pct_change)}</b><small>收盘 {item.close}</small></span>) : <p>暂无完整行情。</p>}</div></IslandCard>
    <IslandCard title="当前有效状态与两种持有区间"><p>本期报告状态：<strong>{PATH_LABELS[research.reported_status ?? "not_mentioned"]}</strong>；当前有效状态：<strong>{research.effective_status ? PATH_LABELS[research.effective_status] : "尚无明确观点"}</strong>。</p><HoldingSummary label="绝对持有" interval={research.strict_holding_interval} /><HoldingSummary label="广义持有" interval={research.broad_holding_interval} /></IslandCard>
    <IslandCard title="历史已结束持有区间"><HoldingHistory label="绝对持有" items={research.historical_strict_intervals} /><HoldingHistory label="广义持有" items={research.historical_broad_intervals} /></IslandCard>
    <IslandCard title="完整收盘行情图"><div className="path-period-switch" aria-label="行情交易日范围">{[20,40,60].map(value => <button type="button" key={value} className={marketDays === value ? "active" : ""} onClick={() => setMarketDays(value)}>最近{value}交易日</button>)}</div>{research.market_support_status === "unsupported" ? <p>暂不支持：不生成伪造行情图。</p> : <><IslandMarketSparkline history={research.market_history ?? []} /><p className="muted">实线只使用完整收盘；盘中点不进入均线。</p></>}</IslandCard>
    <section><h2>路径记录</h2><div className="path-record-list">{research.recent_path?.map(item => <IslandCard key={item.id}><h3>{item.report_date} · {item.path.path_status_label}</h3><p>有效状态：{item.effective_status ? PATH_LABELS[item.effective_status] : "暂无"}。路径记录仅表达报告观点，不绑定当前市场日期。</p>{item.has_detailed_assessment && item.detail_report_id ? <Link to={`/reports/${item.detail_report_id}`}>查看该期详细报告</Link> : <p>仅有路径记录，尚未补充该期原始报告。</p>}</IslandCard>)}</div></section>
    <section><h2>历次详细解读与发布快照</h2><div className="assessment-list">{research.detailed_history?.map(item => <IslandCard key={item.report_id}><h3>{item.report_date} · {item.path.path_status_label}</h3><dl className="assessment-fields"><div><dt>历史路径</dt><dd>{item.assessment.recent_path_summary}</dd></div><div><dt>当期判断</dt><dd>{item.assessment.current_judgement || "本期未提"}</dd></div><div><dt>主要依据</dt><dd>{item.assessment.main_basis || "—"}</dd></div><div><dt>观察条件</dt><dd>{item.assessment.observation_condition || "—"}</dd></div></dl><h4>本报告发布时</h4><IslandMetricGrid market={item.report_snapshot} /><Link to={`/reports/${item.report_id}`}>来源报告</Link></IslandCard>)}</div></section>
    <p className="notice">报告快照保持不变；盘中缓存与最新完整收盘严格分离。研究辅助数据，非生产级行情服务。</p>
  </div>;
}

export function SecurityProxyCard({ observation }: { observation: ViewerObservation }) {
  if (observation.viewer_source_mode === "unavailable") return <IslandCard title="代理观察"><p>暂无可靠的代理证券行情</p></IslandCard>;
  const proxy = observation.security_proxy;
  if (!proxy) return null;
  return <IslandCard title="代理观察"><p className="proxy-observation-intro">正式板块行情暂不可用，以下为固定代理ETF和核心公司观察；每只证券独立展示。</p><div className="proxy-observation-list">{proxy.instruments.map(item => {
    const orderedRecentCloses = item.recent_closes;
    return <article className="proxy-observation-item" key={item.symbol}><header><div><small className="proxy-role">{item.proxy_role === "etf" ? "代理ETF" : "核心公司"}</small><strong>{item.security_name}</strong>{item.coverage_type === "partial" && <small>部分覆盖</small>}</div>{item.quote_status === "available" || item.quote_status === "completed_eod" ? <b className="proxy-quote"><span>{formatSecurityPrice(item.current)}</span><em className={aShareTone(item.pct_change)}>{item.pct_change == null ? "—" : formatPct(item.pct_change)}</em></b> : <span>行情暂不可用</span>}</header><section><h4>近10个交易日</h4><SecurityProxySparkline closes={orderedRecentCloses} />{orderedRecentCloses.length > 0 ? <><div className="proxy-recent-closes">{orderedRecentCloses.map(close => <span key={close.trading_date}><time>{close.trading_date.slice(5)}</time><b>{formatSecurityPrice(close.close)}</b><em className={aShareTone(close.change_pct_from_previous_close)}>{close.change_pct_from_previous_close == null ? "—" : formatPct(close.change_pct_from_previous_close)}</em></span>)}</div>{orderedRecentCloses.length < 10 && <p className="proxy-history-count">当前仅积累 {orderedRecentCloses.length} 个交易日</p>}</> : <p className="proxy-history-empty">暂无足够历史</p>}</section><dl className="proxy-ma-list">{[["MA5", item.ma5, item.distance_to_ma5_pct], ["MA10", item.ma10, item.distance_to_ma10_pct], ["MA20", item.ma20, item.distance_to_ma20_pct]].map(([label, average, distance]) => <div key={String(label)}><dt>{label}</dt><dd>{typeof average === "number" ? formatSecurityPrice(average) : "—"}</dd><dd><span>相对位置</span><b className={aShareTone(typeof distance === "number" ? distance : null)}>{typeof distance === "number" ? formatPct(distance) : "—"}</b></dd></div>)}</dl><footer>{item.data_mode === "completed_eod" ? "最近完整收盘" : "行情时间"}：{item.quote_datetime?.slice(0, 16) ?? "—"}</footer></article>;
  })}</div><p className="proxy-disclosure">{observation.disclosure}</p></IslandCard>;
}

function HoldingSummary({ label, interval }: { label: string; interval?: NonNullable<SectorResearch["strict_holding_interval"]> | null }) {
  if (!interval) return <p><strong>{label}：</strong>当前未进行。</p>;
  if (interval.status !== "active") return <p><strong>{label}：</strong>{interval.calculation_status === "market_insufficient" ? "起点行情不足" : "当前未进行"}。</p>;
  return <div className="holding-summary"><p><strong>{label}：</strong>进行中，正式收益 {formatPct(interval.eod_return)}；起点报告 {interval.start_report_date} / 行情 {interval.start_market_as_of_date}。</p>{interval.intraday_reference_return != null && <p>盘中参考 {formatPct(interval.intraday_reference_return)}（不替代完整收盘正式收益）。</p>}</div>;
}

function HoldingHistory({ label, items }: { label: string; items?: NonNullable<SectorResearch["historical_strict_intervals"]> }) {
  return <div className="holding-history"><h3>{label}</h3>{items?.length ? items.map((item, index) => <p key={`${label}-${item.start_report_date}-${index}`}>{item.start_report_date}（行情{item.start_market_as_of_date ?? "—"}）→ {item.end_report_date}（行情{item.end_market_as_of_date ?? "—"}），{item.trading_days ?? "—"}个交易日，{formatPct(item.eod_return)}，结束状态{PATH_LABELS[item.end_status ?? "watch"]}</p>) : <p>暂无已结束区间。</p>}</div>;
}
