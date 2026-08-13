import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "../routes/router";
import { api } from "../api/client";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import type { IntradayStatus, Principal, RecentTradingDay, Sector } from "../types";
import { formatPct } from "../utils/format";
import { intradaySystemLabel, realtimePresentation, timeOnly } from "../utils/intraday";
import { compareSectors, type StableSectorSort } from "../utils/sector-order";

const shortDate = (value: string | null | undefined) => value ? value.slice(5).replace("-", "/") : "—";
const marketTone = (value: number | null | undefined) => value == null || value === 0 ? "flat" : value > 0 ? "up" : "down";
const maLine = (label: string, value: number | null | undefined) => {
  const displayLabel = label === "EOD MA20" ? "正式MA20" : label;
  if (label === "实时MA5" && value == null) return "实时MA5不足";
  return value == null ? `${displayLabel} —` : `${displayLabel} ${value >= 0 ? "↑" : "↓"}${Math.abs(value).toFixed(2)}%`;
};

function RealtimeCell({ item, system }: { item: Sector; system?: IntradayStatus }) {
  const snapshot = item.intraday_snapshot;
  const presentation = realtimePresentation(item, system);
  const title = [
    `Provider：${snapshot?.provider ?? system?.provider ?? "尚无"}`,
    `角色：${snapshot?.provider_role ?? system?.provider_role ?? "research_provider"}`,
    `最近尝试：${item.intraday_last_attempt_at ?? system?.last_attempt_at ?? "暂无"}`,
    snapshot ? `快照日期：${snapshot.trade_date}` : `状态：${item.intraday_status ?? "provider_failed"}`,
  ].join("\n");
  return <span className="realtime-cell" title={title}><b className={presentation.tone}>{presentation.value}</b>{presentation.detail && <small>{presentation.detail}</small>}</span>;
}

function RecentTen({ days }: { days: RecentTradingDay[] | undefined }) {
  if (!days?.length) return <span>—</span>;
  return <span className="recent-five-mini" aria-label="最近10个交易日逐日涨跌">
    {days.map(item => <i key={item.trade_date} className={item.daily_pct_change > 0 ? "up" : item.daily_pct_change < 0 ? "down" : "flat"} title={`${item.trade_date} ${formatPct(item.daily_pct_change)} 收盘 ${item.close}`}><small>{shortDate(item.trade_date)}</small><b>{formatPct(item.daily_pct_change)}</b></i>)}
  </span>;
}

export function SectorsPage() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [intraday, setIntraday] = useState<IntradayStatus>();
  const [principal, setPrincipal] = useState<Principal>();
  const [visibility, setVisibility] = useState<"default" | "all" | "low">("default");
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("all");
  const [path, setPath] = useState("all");
  const [mentioned, setMentioned] = useState("all");
  const [market, setMarket] = useState("all");
  const [sort, setSort] = useState<StableSectorSort>("research");
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
        const [items, status, me] = await Promise.all([api.sectors(true), api.intradayStatus(), api.me().catch(() => null)]);
        if (!disposed) { setSectors(items); setIntraday(status); setPrincipal(me ?? undefined); failures = 0; }
      }
      catch { failures = Math.min(3, failures + 1); }
      finally { if (!disposed && document.visibilityState === "visible") schedule(); }
    };
    const visible = () => { if (document.visibilityState === "visible") void load(); else window.clearTimeout(timer); };
    document.addEventListener("visibilitychange", visible); void load();
    return () => { disposed = true; window.clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, []);
  const groups = useMemo(() => Array.from(new Map(
    [...sectors].sort((a, b) => a.group_order - b.group_order || a.overall_order - b.overall_order)
      .map(item => [item.group_order, item.group_name]),
  ).entries()).map(([group_order, group_name]) => ({ group_order, group_name })), [sectors]);
  const filtered = useMemo(() => sectors.filter(item =>
    item.sector_name.toLowerCase().includes(search.toLowerCase()) &&
    (search.trim() !== "" || visibility === "all" || visibility === "low" ? visibility !== "low" || item.is_low_attention : !item.is_low_attention) &&
    (group === "all" || item.group_name === group) &&
    (path === "all" || item.current_path_status === path) &&
    (mentioned === "all" || String(item.mentioned_in_latest_published) === mentioned) &&
    (market === "all" || item.data_status === market)
  ).sort((a, b) => compareSectors(a, b, sort)
  ), [sectors, search, visibility, group, path, mentioned, market, sort]);
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
  const hiddenCount = sectors.filter(item => item.is_low_attention).length;
  const supportedMarketPathCount = intraday?.supported_market_path_count ?? sectors.filter(item => item.market_support_status === "supported").length;
  const togglePin = async (item: Sector) => { if (item.is_pinned_for_research) await api.unpinSector(item.sector_key); else await api.pinSector(item.sector_key); setSectors(await api.sectors(true)); };
  return <div className="page sectors-research"><header><h1>板块研究</h1><p>66个报告主题保持不变；行情研究使用67条路径，其中66条支持、恒生科技另计不支持。</p></header>
    <section className="market-system-strip" aria-label="实时行情系统状态"><strong>实时行情 {intraday?.success_count ?? 0}/{supportedMarketPathCount}</strong><span>暂无数据{intraday?.failure_count ?? 0}项</span>{Boolean(intraday?.stale_count) && <span>延迟{intraday?.stale_count}项</span>}<span>不支持{intraday?.unsupported_count ?? 1}项</span><span>更新{timeOnly(intraday?.last_attempt_at)}</span><span>{intradaySystemLabel(intraday)}</span><small title={`Provider：${intraday?.provider ?? "尚无"}；角色：${intraday?.provider_role ?? "research_provider"}`}>研究辅助数据，非生产级行情服务</small></section>
    <div className="visibility-toolbar"><strong>已隐藏低关注板块：{hiddenCount}个</strong><button type="button" onClick={() => setVisibility("default")} className={visibility === "default" ? "active" : ""}>默认关注</button><button type="button" onClick={() => setVisibility("all")} className={visibility === "all" ? "active" : ""}>显示全部行情路径</button><button type="button" onClick={() => setVisibility("low")} className={visibility === "low" ? "active" : ""}>仅低关注</button><small>隐藏不等于删除；搜索始终包含隐藏板块。</small></div>
    <div className="sector-filters" aria-label="板块筛选"><label>搜索<input value={search} onChange={event => setSearch(event.target.value)} /></label><label>一级分组<select value={group} onChange={event => setGroup(event.target.value)}><option value="all">全部</option>{groups.map(item => <option key={item.group_order}>{item.group_name}</option>)}</select></label><label>路径状态<select value={path} onChange={event => setPath(event.target.value)}><option value="all">全部</option><option value="hold">持有</option><option value="watch">观察</option><option value="not_mentioned">未提</option></select></label><label>本期提及<select value={mentioned} onChange={event => setMentioned(event.target.value)}><option value="all">全部</option><option value="true">已提及</option><option value="false">未提及</option></select></label><label>行情状态<select value={market} onChange={event => setMarket(event.target.value)}><option value="all">全部</option><option value="supported">支持</option><option value="proxy">代理</option><option value="short_history">短历史</option><option value="unsupported">不支持</option></select></label><label>组内排序<select value={sort} onChange={event => setSort(event.target.value as StableSectorSort)}><option value="research">稳定热度</option><option value="status">按直播状态</option><option value="date">按观点日期</option><option value="catalog">目录原序</option></select></label></div>
    <nav className="group-jump-nav sector-group-nav" aria-label="板块研究一级分组快捷导航">{filteredGroups.map(item => <button key={item.group_order} type="button" aria-current={activeGroup === item.group_name ? "true" : undefined} onClick={() => { groupTargets.current.get(item.group_name)?.scrollIntoView({ behavior: "smooth", block: "start" }); setActiveGroup(item.group_name); }}>{item.group_name}<small>{item.rows.length}</small></button>)}</nav>
    <section className="holding-explanation" aria-labelledby="holding-explanation-title"><h2 id="holding-explanation-title">持有区间说明</h2><p><strong>绝对持有：</strong>只连续计算“转持、持有”。 <strong>广义持有：</strong>将“强观”也视为持有波段中的风险观察。</p><details><summary>查看详细定义</summary><div><p><strong>绝对持有期：</strong>从最近一次“转持”开始，持续处于“转持、持有”状态；明确转为强观、观察、弱观、转弱、离场或不碰时结束。</p><p><strong>广义持有期：</strong>从最近一次“转持”开始，“强观”仍视为持有波段中的风险观察；转为观察、弱观、转弱、离场或不碰时结束。</p><p>“未提”沿用上一期有效状态。正式收益仅使用完整交易日行情，盘中收益仅作参考。</p></div></details></section>
    <div className="sector-table-wrap table-wrap"><table className="sector-table"><caption>板块研究档案（当前{filtered.length}条行情路径；报告主题66项）</caption><thead><tr><th>板块</th><th>分组</th><th title="本期报告状态 / 延续后的有效状态">本期/有效</th><th>最近10期</th><th>最新观点</th><th>实时行情</th><th>近10日</th><th>10日明细</th><th>持有区间</th><th>MA关系</th><th>数据状态</th></tr></thead><tbody>{filteredGroups.flatMap(({ group_name: groupName, rows }) => [<tr className="sector-group-row" data-group-name={groupName} ref={node => { if (node) groupTargets.current.set(groupName, node); else groupTargets.current.delete(groupName); }} key={`group-${groupName}`}><th colSpan={11}>{groupName}<small>{rows.length}项</small></th></tr>, ...rows.map(item => <tr key={item.sector_key}><th scope="row"><Link to={`/sectors/${item.sector_key}`}>{item.sector_name}</Link>{item.parent_report_topic === "hotel_catering" && <small>报告主题：酒店餐饮</small>}{item.status_changed && <small className="changed-mark">状态变化</small>}{principal?.role === "admin" && <button className="pin-sector" type="button" onClick={() => void togglePin(item)}>{item.is_pinned_for_research ? "取消常驻" : "常驻关注"}</button>}</th><td>{item.group_name}</td><td><span className="status-pair"><small>本期</small><b>{item.current_path_status_label}</b><small>有效</small><b>{item.effective_status_label ?? "暂无"}</b></span></td><td><span className="mini-path-strip">{(item.recent_path ?? []).slice(-10).map(entry => <i key={`${entry.report_id}-${entry.report_date}`} className={`path-${entry.path_status}`} title={`${entry.report_date} ${entry.path_status_label}`}>{entry.path_status_label.slice(0, 1)}</i>)}</span></td><td><span className="two-line-cell" title={item.latest_view ?? "暂无明确观点"}><b>{item.current_path_status_label}</b><small>{shortDate(item.latest_view_date)}</small></span></td><td><RealtimeCell item={item} system={intraday} /></td><td><span className="two-line-cell"><b className={marketTone(item.latest_market?.return_10d)}>{formatPct(item.latest_market?.return_10d)}</b><small>完整EOD</small></span></td><td><RecentTen days={item.recent_10_trading_days} /></td><td><span className="two-line-cell holding-cell" title={`绝对：${item.strict_holding_interval?.start_report_date ?? "—"}起；广义：${item.broad_holding_interval?.start_report_date ?? "—"}起`}><small>绝对 {item.strict_holding_interval?.status === "active" ? formatPct(item.strict_holding_interval.eod_return) : "—"}</small><small>广义 {item.broad_holding_interval?.status === "active" ? formatPct(item.broad_holding_interval.eod_return) : "—"}</small></span></td><td>{item.latest_market ? <span className="two-line-cell ma-cell"><small className={marketTone(item.intraday_snapshot?.intraday_vs_ma5)}>{maLine("实时MA5", item.intraday_snapshot?.intraday_vs_ma5)}</small><small className={marketTone(item.latest_market.close_vs_ma20_pct)}>{maLine("EOD MA20", item.latest_market.close_vs_ma20_pct)}</small></span> : "—"}</td><td><IslandStatusBadge status={item.data_status} /></td></tr>)])}</tbody></table></div>
  </div>;
}
