import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "../routes/router";
import { api } from "../api/client";
import type { IntradayStatus, MarketCoreCurrentQuotes, PrimaryMarketHistoryRow, Principal, Sector } from "../types";
import { formatPct } from "../utils/format";
import { intradaySystemLabel, timeOnly } from "../utils/intraday";

const shortDate = (value: string | null | undefined) => value ? value.slice(5).replace("-", "/") : "—";
const marketTone = (value: number | null | undefined) => value == null || value === 0 ? "flat" : value > 0 ? "up" : "down";
const maLine = (label: string, value: number | null | undefined) => {
  const displayLabel = label === "EOD MA20" ? "正式MA20" : label;
  if (label === "实时MA5" && value == null) return "实时MA5不足";
  return value == null ? `${displayLabel} —` : `${displayLabel} ${value >= 0 ? "↑" : "↓"}${Math.abs(value).toFixed(2)}%`;
};

function LatestViewCell({ item }: { item: Sector }) {
  const fact = item.latest_explicit_view;
  if (!fact) return <span className="two-line-cell"><b>暂无</b><small>无明确报告观点</small></span>;
  const assessment = fact.assessment;
  const statusLabel = assessment.path_status_label.replace(/\*\*|__/g, "");
  const viewpointContext = /^(持有区|观察区|风险转折|回避区)\s*·/.test(assessment.current_judgement ?? "") ? "" : assessment.current_judgement;
  const detail = [assessment.main_basis, assessment.observation_condition].filter(Boolean).join("；");
  const title = [
    `${fact.report_date} · ${statusLabel}`,
    viewpointContext,
    assessment.main_basis,
    assessment.observation_condition,
  ].filter(Boolean).join("\n");
  return <span className="two-line-cell board-latest-view" title={title}>
    <b>{statusLabel}</b>
    <small>{shortDate(fact.report_date)}{detail ? ` · ${detail}` : ""}</small>
  </span>;
}

function RecentTen({ days }: { days: PrimaryMarketHistoryRow[] | undefined }) {
  if (!days?.length) return <span>—</span>;
  return <span className="recent-five-mini" aria-label="最近10个交易日逐日涨跌">
    {days.map(item => <i key={item.trading_date} className={item.daily_pct_change != null && item.daily_pct_change > 0 ? "up" : item.daily_pct_change != null && item.daily_pct_change < 0 ? "down" : "flat"} title={`${item.trading_date} ${formatPct(item.daily_pct_change)} 收盘 ${item.close}`}><small>{shortDate(item.trading_date)}</small><b>{formatPct(item.daily_pct_change)}</b><em>收盘 {item.close.toFixed(2)}</em></i>)}
  </span>;
}

const quoteTime = (value: string | null | undefined) => value?.match(/T(\d{2}:\d{2}:\d{2})/)?.[1] ?? timeOnly(value);

function PrimaryMarketCell({ item, current }: { item: Sector; current?: NonNullable<MarketCoreCurrentQuotes["sectors"]>[number] }) {
  const market = item.primary_market;
  const quote = current?.instruments[0];
  const name = quote?.name || market?.name;
  const code = quote?.security_code || market?.security_code;
  if (!name || !code) return <span className="two-line-cell">—</span>;
  const available = current?.market_status === "available" && quote?.status === "available" && quote.current != null && quote.quote_datetime;
  return <span className="two-line-cell primary-market-cell">
    <b>{name}</b>
    <small className="primary-security-code">{code}</small>
    {available ? <>
      <small>现价 <strong>{quote.current?.toFixed(3)}</strong></small>
      <small className={marketTone(quote.pct_change)}>今日 {formatPct(quote.pct_change)}</small>
      <small>行情时间 {quoteTime(quote.quote_datetime)}</small>
    </> : <small className="market-unavailable">行情暂不可用</small>}
  </span>;
}

function PrimaryTenDay({ item }: { item: Sector }) {
  const market = item.primary_market;
  if (!market?.history_days) return <span>—</span>;
  return <span className="two-line-cell"><b className={marketTone(market.return_10d)}>{formatPct(market.return_10d)}</b><small>{market.history_days}日完整收盘</small></span>;
}

function PrimaryTenDayDetails({ item }: { item: Sector }) {
  const market = item.primary_market;
  if (!market?.history.length) return <span>—</span>;
  return <details className="primary-ten-detail"><summary>查看10日</summary><RecentTen days={market.history} /></details>;
}

function GroupReportDateAxis({ rows }: { rows: Sector[] }) {
  const dates = (rows[0]?.recent_path ?? []).slice(-10);
  return <span className="mini-path-date-axis" aria-label="最近10期报告日期">
    {dates.map(entry => <i key={`${entry.report_id}-${entry.report_date}`}>{shortDate(entry.report_date)}</i>)}
  </span>;
}

export function SectorsPage() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [intraday, setIntraday] = useState<IntradayStatus>();
  const [currentQuotes, setCurrentQuotes] = useState<MarketCoreCurrentQuotes>();
  const [principal, setPrincipal] = useState<Principal>();
  const [showDormant, setShowDormant] = useState(false);
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("all");
  const [path, setPath] = useState("all");
  const [mentioned, setMentioned] = useState("all");
  const [market, setMarket] = useState("all");
  const groupTargets = useRef(new Map<string, HTMLTableRowElement>());
  const [activeGroup, setActiveGroup] = useState("");
  useEffect(() => {
    let disposed = false; let timer = 0; let failures = 0;
    const schedule = () => { timer = window.setTimeout(() => void load(), Math.min(240_000, 45_000 * 2 ** failures)); };
    const load = async () => {
      window.clearTimeout(timer);
      try {
        // Anonymous Viewer reads are intentional.  A 401 from the optional
        // identity endpoint must not discard the already-public sector and
        // market-status responses.
        const [items, status, current, me] = await Promise.all([api.sectors(true), api.intradayStatus(), api.marketCurrent("matrix").catch(() => null), api.me().catch(() => null)]);
        if (!disposed) { setSectors(items); setIntraday(status); setCurrentQuotes(current ?? undefined); setPrincipal(me ?? undefined); failures = 0; }
      }
      catch { failures = Math.min(3, failures + 1); }
      finally { if (!disposed && document.visibilityState === "visible") schedule(); }
    };
    const visible = () => { if (document.visibilityState === "visible") void load(); else window.clearTimeout(timer); };
    document.addEventListener("visibilitychange", visible); void load();
    return () => { disposed = true; window.clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, []);
  const reportTopics = sectors;
  const currentBySector = useMemo(() => new Map((currentQuotes?.sectors ?? []).map(item => [item.sector_key, item])), [currentQuotes]);
  const groups = useMemo(() => Array.from(new Map(
    [...reportTopics].sort((a, b) => a.group_order - b.group_order || a.overall_order - b.overall_order)
      .map(item => [item.group_order, item.group_name]),
  ).entries()).map(([group_order, group_name]) => ({ group_order, group_name })), [reportTopics]);
  const filtered = useMemo(() => reportTopics.filter(item =>
    item.sector_name.toLowerCase().includes(search.toLowerCase()) &&
    (showDormant || !item.is_dormant_20d || Boolean(search.trim())) &&
    (group === "all" || item.group_name === group) &&
    (path === "all" || item.current_path_status === path) &&
    (mentioned === "all" || String(item.mentioned_in_latest_published) === mentioned) &&
    (market === "all" || item.data_status === market)
  ).sort((a, b) => a.group_order - b.group_order || a.overall_order - b.overall_order
  ), [reportTopics, search, showDormant, group, path, mentioned, market]);
  const filteredGroups = useMemo(() => groups.map(item => ({ ...item, rows: filtered.filter(sector => sector.group_order === item.group_order) })).filter(item => item.rows.length), [groups, filtered]);
  useEffect(() => {
    if (!filteredGroups.some(item => item.group_name === activeGroup)) setActiveGroup(filteredGroups[0]?.group_name ?? "");
  }, [filteredGroups, activeGroup]);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(item => item.isIntersecting).sort((a, b) => Math.abs(a.boundingClientRect.top) - Math.abs(b.boundingClientRect.top));
      const name = (visible[0]?.target as HTMLElement | undefined)?.dataset.groupName;
      if (name) setActiveGroup(name);
    }, { rootMargin: "-120px 0px -70% 0px" });
    groupTargets.current.forEach(item => observer.observe(item));
    return () => observer.disconnect();
  }, [filteredGroups]);
  const hiddenCount = reportTopics.filter(item => item.is_dormant_20d).length;
  const supportedMarketPathCount = intraday?.supported_market_path_count ?? sectors.filter(item => item.market_support_status === "supported").length;
  const togglePin = async (item: Sector) => { if (item.is_pinned_for_research) await api.unpinSector(item.sector_key); else await api.pinSector(item.sector_key); setSectors(await api.sectors(true)); };
  return <div className="page sectors-research"><header><h1>板块研究</h1><p>74个显示对象中包含71个active Report Object；行情观察始终使用固定主标的，恒生科技保持跨市场不支持。</p></header>
    <section className="market-system-strip" aria-label="实时行情系统状态"><strong>实时行情 {intraday?.success_count ?? 0}/{supportedMarketPathCount}</strong><span>暂无数据{intraday?.failure_count ?? 0}项</span>{Boolean(intraday?.stale_count) && <span>延迟{intraday?.stale_count}项</span>}<span>不支持{intraday?.unsupported_count ?? 1}项</span><span>更新{timeOnly(intraday?.last_attempt_at)}</span><span>{intradaySystemLabel(intraday)}</span><small title={`Provider：${intraday?.provider ?? "尚无"}；角色：${intraday?.provider_role ?? "research_provider"}`}>研究辅助数据，非生产级行情服务</small></section>
    <div className="visibility-toolbar"><label><input type="checkbox" checked={showDormant} onChange={event => setShowDormant(event.target.checked)} /> 显示20日未提板块{hiddenCount ? `（${hiddenCount}）` : ""}</label>{!showDormant && hiddenCount > 0 && <small>已隐藏 {hiddenCount} 个连续20日未提板块；搜索可直接显示匹配项。</small>}<small>仅改变默认列表可见性，不影响历史或行情采集。</small></div>
    <div className="sector-filters" aria-label="板块筛选"><label>搜索<input value={search} onChange={event => setSearch(event.target.value)} /></label><label>一级分组<select value={group} onChange={event => setGroup(event.target.value)}><option value="all">全部</option>{groups.map(item => <option key={item.group_order}>{item.group_name}</option>)}</select></label><label>路径状态<select value={path} onChange={event => setPath(event.target.value)}><option value="all">全部</option><option value="hold">持有</option><option value="watch">观察</option><option value="not_mentioned">未提</option></select></label><label>本期提及<select value={mentioned} onChange={event => setMentioned(event.target.value)}><option value="all">全部</option><option value="true">已提及</option><option value="false">未提及</option></select></label><label>行情状态<select value={market} onChange={event => setMarket(event.target.value)}><option value="all">全部</option><option value="supported">支持</option><option value="proxy">代理</option><option value="short_history">短历史</option><option value="unsupported">不支持</option></select></label></div>
    <nav className="group-jump-nav sector-group-nav" aria-label="板块研究一级分组快捷导航">{filteredGroups.map(item => <button key={item.group_order} type="button" aria-current={activeGroup === item.group_name ? "true" : undefined} onClick={() => { groupTargets.current.get(item.group_name)?.scrollIntoView({ behavior: "smooth", block: "start" }); setActiveGroup(item.group_name); }}>{item.group_name}<small>{item.rows.length}</small></button>)}</nav>
    <section className="holding-explanation" aria-labelledby="holding-explanation-title"><h2 id="holding-explanation-title">持有区间说明</h2><p><strong>绝对持有：</strong>只连续计算“转持、持有”。 <strong>广义持有：</strong>将“强观、转弱”视为持有波段中的风险观察。</p><details><summary>查看详细定义</summary><div><p><strong>绝对持有期：</strong>从最近一次“转持”开始，持续处于“转持、持有”状态；明确转为强观、观察、弱观、转弱、离场或不碰时结束。</p><p><strong>广义持有期：</strong>从最近一次“转持”开始，“强观、转弱”仍视为持有波段中的风险观察；转为观察、弱观、离场或不碰时结束。</p><p>“未提”沿用上一期有效状态。正式收益仅使用完整交易日行情，盘中收益仅作参考。</p></div></details></section>
    <div className="sector-table-wrap table-wrap"><table className="sector-table"><caption>板块研究档案（当前{filtered.length}个显示对象；71个active Report Object）</caption><thead><tr><th>板块</th><th>分组</th><th title="本期报告状态 / 延续后的有效状态">本期/有效</th><th>最近10期</th><th>最新观点</th><th>当前/最近行情</th><th>近10日</th><th>查看10日</th><th>持有区间</th><th>MA关系</th><th>操作</th></tr></thead><tbody>{filteredGroups.flatMap(({ group_name: groupName, rows }) => [<tr className="sector-group-row" data-group-name={groupName} ref={node => { if (node) groupTargets.current.set(groupName, node); else groupTargets.current.delete(groupName); }} key={`group-${groupName}`}><th scope="rowgroup">{groupName}<small>{rows.length}项</small></th><td colSpan={2} aria-hidden="true" /><td className="group-recent10-axis"><GroupReportDateAxis rows={rows} /></td><td colSpan={7} aria-hidden="true" /></tr>, ...rows.map(item => <tr key={item.sector_key}><th scope="row"><Link to={`/sectors/${item.sector_key}`}>{item.sector_name}</Link>{item.status_changed && <small className="changed-mark">状态变化</small>}{principal?.role === "admin" && <button className="pin-sector" type="button" onClick={() => void togglePin(item)}>{item.is_pinned_for_research ? "取消常驻" : "常驻关注"}</button>}</th><td>{item.group_name}</td>
<td><span className="status-pair"><small>本期</small><b>{item.current_path_status_label}</b><small>有效</small><b>{item.effective_status_label ?? "暂无"}</b>{item.effective_source_report_date && <small className="effective-source">来源 {item.effective_source_report_date.slice(5)}{item.effective_derived_from_transition ? " · 由转持延续" : ""}</small>}</span></td>
<td><span className="mini-path-strip">{(item.recent_path ?? []).slice(-10).map(entry => <i key={`${entry.report_id}-${entry.report_date}`} className={`path-${entry.path_status}`} title={`${entry.report_date} ${entry.path_status_label}`}><b>{entry.path_status_label.slice(0, 1)}</b></i>)}</span></td>
<td><LatestViewCell item={item} /></td>
<td><PrimaryMarketCell item={item} current={currentBySector.get(item.sector_key)} /></td>
<td><PrimaryTenDay item={item} /></td>
<td><PrimaryTenDayDetails item={item} /></td>
<td><span className="two-line-cell holding-cell" title={`绝对：${item.strict_holding_interval?.start_report_date ?? "—"}起；广义：${item.broad_holding_interval?.start_report_date ?? "—"}起`}><small>绝对 {item.strict_holding_interval?.status === "active" ? shortDate(item.strict_holding_interval.start_report_date) + " → 至今" : "—"}</small><small>广义 {item.broad_holding_interval?.status === "active" ? shortDate(item.broad_holding_interval.start_report_date) + " → 至今" : "—"}</small></span></td>
<td>{item.primary_market?.close != null ? <span className="two-line-cell ma-cell"><small className={marketTone(item.primary_market.close_vs_ma5_pct)}>{maLine("MA5", item.primary_market.close_vs_ma5_pct)}</small><small className={marketTone(item.primary_market.close_vs_ma10_pct)}>{maLine("MA10", item.primary_market.close_vs_ma10_pct)}</small><small className={marketTone(item.primary_market.close_vs_ma20_pct)}>{maLine("MA20", item.primary_market.close_vs_ma20_pct)}</small></span> : "—"}</td>
<td><Link className="sector-row-action" to={`/sectors/${item.sector_key}`}>查看</Link></td></tr>)])}</tbody></table></div>
  </div>;
}
