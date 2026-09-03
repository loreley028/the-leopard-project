import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "../routes/router";
import { api, publicResourcePath } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import { BroadMarketOverview, MarketCoreShanghaiReader } from "../components/market/MarketCoreReader";
import { DefenseDistanceTrend } from "../components/market/DefenseDistanceTrend";
import type { DefenseLineValidation, EnhancedReport, MarketCoreBroadMarket, MarketCoreCurrentQuotes, MarketCoreShanghai, MarketSnapshot, PathMatrix, Report, ReportDefense, SectorAssessment } from "../types";
import { formatPct } from "../utils/format";
import { judgementDetail, pdfGroup } from "../utils/judgement";
import { useMarketCurrentPolling } from "../hooks/useMarketCurrentPolling";

const IslandPathMatrix = lazy(() => import("../components/island/IslandPathMatrix").then(module => ({ default: module.IslandPathMatrix })));
const PdfPagePreview = lazy(() => import("../components/PdfPagePreview").then(module => ({ default: module.PdfPagePreview })));

const GROUP_ORDER = ["B1 继续持有", "B2 重点观察区", "B3 当前不碰"];
const chineseDate = (value: string | null) => value ? `${Number(value.slice(0, 4))}年${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日` : "待确认日期";
const pct = (value: number | null | undefined) => value == null ? "—" : formatPct(value);
const ratio = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}x`;

const point = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signedPoint = (value: number | null | undefined) => value == null ? "—" : `${value > 0 ? "+" : ""}${point(value)}`;
const positionLabel: Record<NonNullable<ReportDefense["defense_position"]>, string> = {
  above_defense_line: "攻防线上方",
  below_defense_line: "攻防线下方",
  at_defense_line: "攻防线附近 / 等于攻防线",
};
const validationPositionLabel: Record<DefenseLineValidation["close_position"], string> = {
  close_above_defense_line: "收盘在线上",
  close_below_defense_line: "收盘在线下",
  close_at_defense_line: "收盘与线相等",
};
const signedTone = (value: number | null | undefined) => value == null || value === 0 ? "a-share-neutral" : value > 0 ? "a-share-positive" : "a-share-negative";
const positionTone = (position: ReportDefense["defense_position"] | DefenseLineValidation["close_position"] | null) => (
  position === "above_defense_line" || position === "close_above_defense_line" ? "a-share-positive"
    : position === "below_defense_line" || position === "close_below_defense_line" ? "a-share-negative" : "a-share-neutral"
);

function ReportOverview({ enhanced, market, broad }: { enhanced: EnhancedReport; market: MarketCoreShanghai | null; broad: MarketCoreBroadMarket | null }) {
  const { report } = enhanced;
  const defense = enhanced.report_defense;
  const defenseSource = defense.defense_line_source === "website_md" ? "网站MD结构化字段" : defense.defense_line_source === "parsed_defense_line" ? "结构化攻防线" : defense.defense_line_source === "market_path" ? "大盘路径" : defense.defense_line_source === "core_view" ? "核心判断安全回退" : null;
  const liveCurrent = market?.live.status === "available" ? market.live.current : null;
  const distancePoints = liveCurrent != null && defense.defense_line_value != null ? liveCurrent - defense.defense_line_value : null;
  const distancePct = distancePoints != null && defense.defense_line_value ? distancePoints / defense.defense_line_value * 100 : null;
  const defensePosition = distancePoints == null ? null : distancePoints > 0 ? "above_defense_line" : distancePoints < 0 ? "below_defense_line" : "at_defense_line";
  const validations = enhanced.recent_defense_line_validations;
  const intradayOverlay = enhanced.intraday_defense_overlay;
  return <div className="report-overview-grid">
    <IslandCard title="核心观点">
      <div className="core-insight-panel">
        <MarketCoreShanghaiReader market={market} includeHistory={false} />
        <section className="report-priority-facts" aria-label="报告核心定性和执行结论">
          <div><p className="eyebrow">核心定性</p><p>{report.core_view || "报告未单列核心定性。"}</p>{report.reader_fact_provenance?.core_characterization?.source_page && <small>来源：PDF 第 {report.reader_fact_provenance.core_characterization.source_page} 页</small>}</div>
          <div><p className="eyebrow">执行结论</p><p>{report.market_path || "报告未单列执行结论。"}</p>{report.reader_fact_provenance?.execution_conclusion?.source_page && <small>来源：PDF 第 {report.reader_fact_provenance.execution_conclusion.source_page} 页</small>}</div>
        </section>
        <section className="defense-line-panel" aria-label="猎豹攻防线">
          <div className="defense-level"><span>猎豹攻防点<small>来自 {report.report_date ?? "—"} 报告</small></span><strong>{defense.defense_line_value == null ? "报告未单列" : point(defense.defense_line_value)}</strong></div>
          {defense.defense_line_value != null && <div className="defense-live-position">
            <span>当前相对攻防线</span><strong className={signedTone(distancePoints)}>{signedPoint(distancePoints)}</strong>
            <em className={signedTone(distancePct)}>{pct(distancePct)}</em>
            <small className={positionTone(defensePosition)}>{defensePosition ? positionLabel[defensePosition] : "等待当前行情"}</small>
          </div>}
          <dl>
            <div><dt>站上条件</dt><dd>{defense.stand_above_condition ?? "报告未单列站上后的确认条件。"}</dd></div>
            <div><dt>跌破条件</dt><dd>{defense.break_below_condition ?? "报告未单列跌破后的应对条件。"}</dd></div>
            <div><dt>验证条件</dt><dd>{defense.validation_conditions ?? "继续按报告原文观察时间、宽度、量能或资金确认。"}</dd></div>
          </dl>
          <p className="defense-source">攻防线来源：{defenseSource ?? "报告未单列"}。报告观点与当前市场辅助按各自日期语义展示。</p>
        </section>
        <section className="defense-validation-panel" aria-label="近10个交易日猎豹攻防点">
          <div className="defense-validation-heading"><div><p className="eyebrow">近10个交易日猎豹攻防点</p><p>按前一份报告提出的攻防线，对照下一受控交易日上证指数实际收盘；不构成预测评分。</p></div><span>自然积累</span></div>
          <div className="defense-validation-table" role="table" aria-label="攻防验证明细">
            <div className="defense-validation-row defense-validation-header" role="row"><span>交易日</span><span>攻防线来源</span><span>攻防线</span><span>上证收盘</span><span>距攻防线</span><span>收盘位置</span></div>
            {intradayOverlay && <div className="defense-validation-row defense-validation-intraday" role="row">
              <div role="cell"><small>交易日</small><strong>{intradayOverlay.trading_date.slice(5)} · {intradayOverlay.session_state === "lunch_break" ? "午间" : "盘中"}</strong></div>
              <div role="cell"><small>攻防线来源</small><strong>来自 {intradayOverlay.source_report_date.slice(5)} 报告</strong></div>
              <div role="cell"><small>攻防线</small><strong>{point(intradayOverlay.defense_line_value)}</strong></div>
              <div role="cell"><small>上证当前</small><strong>{point(intradayOverlay.index_current)}</strong></div>
              <div role="cell"><small>距攻防线</small><strong className={signedTone(intradayOverlay.distance_points)}>{signedPoint(intradayOverlay.distance_points)}</strong><em className={signedTone(intradayOverlay.distance_pct)}>{pct(intradayOverlay.distance_pct)}</em></div>
              <div role="cell"><small>当前位置</small><strong className={positionTone(intradayOverlay.close_position)}>{validationPositionLabel[intradayOverlay.close_position]}</strong></div>
            </div>}
            {validations.map(item => <div className="defense-validation-row" role="row" key={`${item.source_report_id}-${item.trading_date}`}>
              <div role="cell"><small>交易日</small><strong>{item.trading_date.slice(5)}</strong></div>
              <div role="cell"><small>攻防线来源</small><strong>来自 {item.source_report_date.slice(5)} 报告</strong></div>
              <div role="cell"><small>攻防线</small><strong>{point(item.defense_line_value)}</strong></div>
              <div role="cell"><small>上证收盘</small><strong>{point(item.index_close)}</strong></div>
              <div role="cell"><small>距攻防线</small><strong className={signedTone(item.distance_points)}>{signedPoint(item.distance_points)}</strong><em className={signedTone(item.distance_pct)}>{pct(item.distance_pct)}</em></div>
              <div role="cell"><small>收盘位置</small><strong className={positionTone(item.close_position)}>{validationPositionLabel[item.close_position]}</strong></div>
            </div>)}
          </div>
          {validations.length === 0 && <p className="defense-validation-empty">攻防验证记录将随交易日自然积累。</p>}
          <p className="defense-validation-count">当前已积累 {validations.length} / 10 条完整验证记录。</p>
          <DefenseDistanceTrend points={enhanced.defense_line_trend} intradayOverlay={intradayOverlay} />
        </section>
        <BroadMarketOverview shanghai={market} broad={broad} />
      </div>
    </IslandCard>
    <IslandCard title="风险提示"><p className={report.risk_warning ? "" : "report-risk-empty"}>{report.risk_warning || "本报告未单列风险提示。"}</p></IslandCard>
  </div>;
}

function MarketStrip({ market, holding }: { market: MarketSnapshot | null; holding: SectorAssessment["active_holding_interval"] }) {
  return <div className="assessment-market-strip" aria-label="行情辅助">
    <strong>行情辅助</strong><span>日期 {market?.trade_date ?? "—"}</span><span>当日 {pct(market?.daily_pct_change)}</span>
    <span>近5日 {pct(market?.return_5d)}</span><span>近10日 {pct(market?.return_10d)}</span><span>近20日 {pct(market?.return_20d)}</span>
    <span>相对MA5 {pct(market?.close_vs_ma5_pct)}</span><span>相对MA20 {pct(market?.close_vs_ma20_pct)}</span>
    <span>量/MA5 {ratio(market?.volume_ratio_5d)}</span><span>量/MA20 {ratio(market?.volume_ratio_20d)}</span>
    <span>本轮持有 {holding?.status === "active" ? pct(holding.return_pct) : "—"}</span>
  </div>;
}

function AssessmentTable({ title, items }: { title: string; items: SectorAssessment[] }) {
  return <section className="pdf-assessment-group"><h3>{title}</h3><div className="table-wrap"><table className="pdf-assessment-table"><caption className="sr-only">{title}</caption>
    <thead><tr><th>板块</th><th>历史路径（最近转折）</th><th>当期判断</th><th>主要依据</th><th>观察条件</th></tr></thead>
    <tbody>{items.map(item => { const detail = judgementDetail(item.current_path_status, item.current_judgement); return <Fragment key={item.id}><tr>
      <th scope="row"><Link to={`/sectors/${item.sector_key}`}>{item.sector_name}</Link></th>
      <td data-label="历史路径（最近转折）">{item.recent_path_summary || "—"}</td>
      <td data-label="当期判断"><span className={`path-chip path-${item.current_path_status}`}>{item.path_status_label}</span>{detail && <p>{detail}</p>}</td>
      <td data-label="主要依据">{item.main_basis || "—"}</td>
      <td data-label="观察条件">{item.observation_condition || "—"}</td>
    </tr><tr className="market-strip-row"><td colSpan={5}><MarketStrip market={item.market} holding={item.active_holding_interval} /></td></tr></Fragment>; })}</tbody>
  </table></div></section>;
}

export function ReportDetailPage({ latest = false }: { latest?: boolean }) {
  const { reportId: routeReportId = "" } = useParams();
  const location = useLocation();
  const [latestReportId, setLatestReportId] = useState("");
  const [latestReport, setLatestReport] = useState<Report | null>(null);
  const reportId = latest ? latestReportId : routeReportId;
  const [period, setPeriod] = useState("20");
  const [enhanced, setEnhanced] = useState<EnhancedReport | null>();
  const [marketCoreShanghai, setMarketCoreShanghai] = useState<MarketCoreShanghai | null>(null);
  const [broadMarket, setBroadMarket] = useState<MarketCoreBroadMarket | null>(null);
  const [matrix, setMatrix] = useState<PathMatrix | null>(null);
  const [matrixCurrent, setMatrixCurrent] = useState<MarketCoreCurrentQuotes | null>(null);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [matrixRequestedFor, setMatrixRequestedFor] = useState("");
  const pathSectionRef = useRef<HTMLElement | null>(null);
  useEffect(() => { if (latest) api.latestReport().then(item => { setLatestReport(item); setLatestReportId(item.id); }).catch(() => setEnhanced(null)); }, [latest]);
  useEffect(() => { if (reportId) api.enhancedReport(reportId).then(setEnhanced).catch(() => setEnhanced(null)); }, [reportId]);
  useEffect(() => { api.marketShanghai().then(setMarketCoreShanghai).catch(() => setMarketCoreShanghai(null)); }, []);
  useEffect(() => { api.marketBroad().then(setBroadMarket).catch(() => setBroadMarket(null)); }, []);
  const refreshOverviewCurrent = useCallback(async () => {
    const current = await api.marketCurrent("overview");
    const quoteBySymbol = new Map(current.quotes.map(item => [item.symbol, item]));
    setMarketCoreShanghai(previous => previous ? { ...previous, live: quoteBySymbol.get(previous.symbol) ?? previous.live } : previous);
    setBroadMarket(previous => previous ? {
      ...previous,
      cache_hit: current.cache_hit,
      provider_request_count: current.provider_request_count,
      anchors: previous.anchors.map(item => ({ ...item, live: quoteBySymbol.get(item.symbol) ?? item.live })),
    } : previous);
    return current;
  }, []);
  useMarketCurrentPolling(refreshOverviewCurrent, Boolean(marketCoreShanghai || broadMarket));
  const refreshMatrixCurrent = useCallback(async () => { const result = await api.marketCurrent("matrix"); setMatrixCurrent(result); return result; }, []);
  useMarketCurrentPolling(refreshMatrixCurrent, Boolean(matrix), 60_000);
  const grouped = useMemo(() => {
    const result = new Map<string, SectorAssessment[]>();
    for (const item of enhanced?.sector_assessments.filter(value => value.explicitly_mentioned) ?? []) {
      const group = pdfGroup(item.current_path_status); result.set(group, [...(result.get(group) ?? []), item]);
    }
    return result;
  }, [enhanced]);
  useEffect(() => {
    if (!reportId || !enhanced) return;
    if (typeof IntersectionObserver === "undefined") {
      setMatrixRequestedFor(reportId);
      return;
    }
    const target = pathSectionRef.current;
    if (!target) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setMatrixRequestedFor(reportId);
        observer.disconnect();
      }
    }, { rootMargin: "400px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [enhanced, reportId]);
  useEffect(() => {
    setMatrix(null);
    setMatrixCurrent(null);
    if (!reportId || matrixRequestedFor !== reportId) return;
    let active = true;
    api.pathMatrix(reportId, period).then(value => { if (active) setMatrix(value); }).catch(() => { if (active) setMatrix(null); });
    return () => { active = false; };
  }, [matrixRequestedFor, period, reportId]);
  if (enhanced === undefined) return latestReport ? <article className="page enhanced-report report-summary-loading">
    <header className="report-header"><div><IslandStatusBadge status={latestReport.status} /><p className="eyebrow">直播总结动态加强版 · {chineseDate(latestReport.report_date)}</p><h1>{latestReport.title}</h1></div></header>
    <section className="report-priority-facts" aria-label="报告核心内容">
      <div><p className="eyebrow">核心定性</p><p>{latestReport.core_view || "报告未单列核心定性。"}</p></div>
      <div><p className="eyebrow">执行结论</p><p>{latestReport.market_path || "报告未单列执行结论。"}</p></div>
    </section>
    <p role="status">详细报告与行情辅助加载中…</p>
  </article> : <p role="status">加载报告…</p>;
  if (!enhanced) return <p role="alert">暂无已发布报告。</p>;
  const { report } = enhanced;
  const origin = (location.state as { from?: string } | null)?.from === "library" ? "报告库" : "最新报告";
  const mentioned = enhanced.sector_assessments.filter(item => item.explicitly_mentioned);
  const unmentioned = enhanced.sector_assessments.length - mentioned.length;
  return <article className="page enhanced-report">
    {!latest && <nav className="breadcrumbs" aria-label="面包屑"><Link to={origin === "报告库" ? "/reports" : "/"}>{origin}</Link><span>/</span><span>{report.report_date}</span></nav>}
    <header className="report-header"><div><IslandStatusBadge status={report.status} /><p className="eyebrow">直播总结动态加强版 · {chineseDate(report.report_date)}</p><h1>{report.title}</h1></div><div className="date-contract"><span>报告日期<strong>{report.report_date}</strong></span><span>报告核心观点<strong>攻防线与板块观点</strong></span></div></header>
    <nav className="report-tabs" aria-label="增强报告章节"><a href="#overview">报告概览</a><a href="#path" onClick={() => setMatrixRequestedFor(reportId)}>历史路径</a><a href="#assessments">板块观点</a><a href="#source">原始PDF</a></nav>
    <section id="overview"><h2>报告概览</h2><ReportOverview enhanced={enhanced} market={marketCoreShanghai} broad={broadMarket} /></section>
    <section id="path" ref={pathSectionRef}><h2>历史路径矩阵</h2>{matrix ? <Suspense fallback={<p>路径矩阵组件加载中…</p>}><IslandPathMatrix matrix={matrix} currentMarket={matrixCurrent} period={period} onPeriodChange={setPeriod} /></Suspense> : <p>{matrixRequestedFor === reportId ? "路径矩阵加载中…" : "滚动到此处后加载路径矩阵。"}</p>}</section>
    <section id="assessments"><h2>{chineseDate(report.report_date)}板块观点详细汇总</h2><p className="muted">按本期结构化报告事实分组展示五列主体；路径历史与详细观点分别保存。</p>{GROUP_ORDER.map(group => grouped.get(group)?.length ? <AssessmentTable key={group} title={group} items={grouped.get(group)!} /> : null)}<details className="advanced-review"><summary>本期未提及 {unmentioned} 个板块</summary><p>“未提”只表示本期报告没有明确观点，不代表既有观点失效。</p></details></section>
    <section id="source"><h2>原始PDF</h2>{previewLoaded ? <Suspense fallback={<p>PDF预览组件加载中…</p>}><PdfPagePreview reportId={report.id} /></Suspense> : <div className="pdf-preview-placeholder"><p>打开或刷新报告不会请求PDF；点击后仅加载内存渲染的逐页图片，不会写入下载目录。</p><button type="button" onClick={() => setPreviewLoaded(true)}>加载逐页预览</button></div>}<p><a href={publicResourcePath(report.pdf_download_url)}>下载原始PDF</a></p><p>{enhanced.data_notice} 来源追溯由Admin保留，Viewer正文不重复展示原文摘录。</p></section>
  </article>;
}
