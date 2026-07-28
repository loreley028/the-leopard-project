import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import type { IntradayStatus, Principal, RecentTradingDay, Sector } from "../types";
import { formatPct } from "../utils/format";
import { intradaySystemLabel, realtimePresentation, timeOnly } from "../utils/intraday";

const STATUS_RANK: Record<string, number> = { turn_hold: 0, hold: 1, strong_watch: 2, watch: 3, weak_watch: 4, turn_weak: 5, exit: 6, avoid: 7, not_mentioned: 8 };

const shortDate = (value: string | null | undefined) => value ? value.slice(5).replace("-", "/") : "—";
const marketTone = (value: number | null | undefined) => value == null || value === 0 ? "flat" : value > 0 ? "up" : "down";
const maLine = (label: string, value: number | null | undefined) => value == null ? `${label} —` : `${label} ${value >= 0 ? "↑" : "↓"}${Math.abs(value).toFixed(2)}%`;

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

function RecentFive({ days }: { days: RecentTradingDay[] | undefined }) {
  if (!days?.length) return <span>—</span>;
  return <span className="recent-five-mini" aria-label="最近5个交易日逐日涨跌">
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
  const [sort, setSort] = useState("research");
  useEffect(() => {
    const load = () => { void Promise.all([api.sectors(true), api.intradayStatus(), api.me()]).then(([items, status, me]) => { setSectors(items); setIntraday(status); setPrincipal(me); }); };
    load(); const timer = window.setInterval(load, 60_000); return () => window.clearInterval(timer);
  }, []);
  const groups = Array.from(new Set(sectors.map(item => item.group_name)));
  const filtered = useMemo(() => sectors.filter(item =>
    item.sector_name.toLowerCase().includes(search.toLowerCase()) &&
    (search.trim() !== "" || visibility === "all" || visibility === "low" ? visibility !== "low" || item.is_low_attention : !item.is_low_attention) &&
    (group === "all" || item.group_name === group) &&
    (path === "all" || item.current_path_status === path) &&
    (mentioned === "all" || String(item.mentioned_in_latest_published) === mentioned) &&
    (market === "all" || item.data_status === market)
  ).sort((a, b) => sort === "daily" ? (b.latest_market?.daily_pct_change ?? -999) - (a.latest_market?.daily_pct_change ?? -999) : sort === "five" ? (b.latest_market?.return_5d ?? -999) - (a.latest_market?.return_5d ?? -999) : sort === "date" ? (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "") : sort === "group" ? a.group_order - b.group_order || a.overall_order - b.overall_order : sort === "status" ? (STATUS_RANK[a.current_path_status] ?? 99) - (STATUS_RANK[b.current_path_status] ?? 99) || (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "") || a.overall_order - b.overall_order : Number(b.mentioned_in_latest_published) - Number(a.mentioned_in_latest_published) || Number(b.status_changed) - Number(a.status_changed) || (STATUS_RANK[a.current_path_status] ?? 99) - (STATUS_RANK[b.current_path_status] ?? 99) || (b.latest_view_date ?? "").localeCompare(a.latest_view_date ?? "") || a.group_order - b.group_order || a.overall_order - b.overall_order
  ), [sectors, search, visibility, group, path, mentioned, market, sort]);
  const hiddenCount = sectors.filter(item => item.is_low_attention).length;
  const togglePin = async (item: Sector) => { if (item.is_pinned_for_research) await api.unpinSector(item.sector_key); else await api.pinSector(item.sector_key); setSectors(await api.sectors(true)); };
  return <div className="page sectors-research"><header><h1>板块研究</h1><p>66个业务板块纵向档案；观点来自已发布PDF，行情只作客观辅助。</p></header>
    <section className="market-system-strip" aria-label="实时行情系统状态"><strong>实时行情 {intraday?.success_count ?? 0}/65</strong><span>暂无数据{intraday?.failure_count ?? 0}项</span>{Boolean(intraday?.stale_count) && <span>延迟{intraday?.stale_count}项</span>}<span>不支持{intraday?.unsupported_count ?? 1}项</span><span>更新{timeOnly(intraday?.last_attempt_at)}</span><span>{intradaySystemLabel(intraday)}</span><small title={`Provider：${intraday?.provider ?? "尚无"}；角色：${intraday?.provider_role ?? "research_provider"}`}>研究辅助数据，非生产级行情服务</small></section>
    <div className="visibility-toolbar"><strong>已隐藏低关注板块：{hiddenCount}个</strong><button type="button" onClick={() => setVisibility("default")} className={visibility === "default" ? "active" : ""}>默认关注</button><button type="button" onClick={() => setVisibility("all")} className={visibility === "all" ? "active" : ""}>显示全部66项</button><button type="button" onClick={() => setVisibility("low")} className={visibility === "low" ? "active" : ""}>仅低关注</button><small>隐藏不等于删除；搜索始终包含隐藏板块。</small></div>
    <div className="sector-filters" aria-label="板块筛选"><label>搜索<input value={search} onChange={event => setSearch(event.target.value)} /></label><label>一级分组<select value={group} onChange={event => setGroup(event.target.value)}><option value="all">全部</option>{groups.map(item => <option key={item}>{item}</option>)}</select></label><label>路径状态<select value={path} onChange={event => setPath(event.target.value)}><option value="all">全部</option><option value="hold">持有</option><option value="watch">观察</option><option value="not_mentioned">未提</option></select></label><label>本期提及<select value={mentioned} onChange={event => setMentioned(event.target.value)}><option value="all">全部</option><option value="true">已提及</option><option value="false">未提及</option></select></label><label>行情状态<select value={market} onChange={event => setMarket(event.target.value)}><option value="all">全部</option><option value="supported">支持</option><option value="proxy">代理</option><option value="short_history">短历史</option><option value="unsupported">不支持</option></select></label><label>排序<select value={sort} onChange={event => setSort(event.target.value)}><option value="research">研究优先</option><option value="status">按直播状态</option><option value="daily">按完整日涨跌</option><option value="five">按近5日表现</option><option value="date">按观点日期</option><option value="group">按一级分组</option></select></label></div>
    <div className="sector-table-wrap table-wrap"><table className="sector-table"><caption>板块研究档案（当前{filtered.length}项，完整目录66项）</caption><thead><tr><th>板块</th><th>分组</th><th title="本期报告状态 / 延续后的有效状态">本期/有效</th><th>最近10期</th><th>最新观点</th><th>实时行情</th><th>近5日</th><th>5日明细</th><th>持有区间</th><th>MA关系</th><th>数据状态</th></tr></thead><tbody>{filtered.map(item => <tr key={item.sector_key}><th scope="row"><Link to={`/sectors/${item.sector_key}`}>{item.sector_name}</Link>{item.status_changed && <small className="changed-mark">状态变化</small>}{principal?.role === "admin" && <button className="pin-sector" type="button" onClick={() => void togglePin(item)}>{item.is_pinned_for_research ? "取消常驻" : "常驻关注"}</button>}</th><td>{item.group_name}</td><td><span className="status-pair"><small>本期</small><b>{item.current_path_status_label}</b><small>有效</small><b>{item.effective_status_label ?? "暂无"}</b></span></td><td><span className="mini-path-strip">{(item.recent_path ?? []).slice(-10).map(entry => <i key={`${entry.report_id}-${entry.report_date}`} className={`path-${entry.path_status}`} title={`${entry.report_date} ${entry.path_status_label}`}>{entry.path_status_label.slice(0, 1)}</i>)}</span></td><td><span className="two-line-cell" title={item.latest_view ?? "暂无明确观点"}><b>{item.current_path_status_label}</b><small>{shortDate(item.latest_view_date)}</small></span></td><td><RealtimeCell item={item} system={intraday} /></td><td><span className="two-line-cell"><b className={marketTone(item.latest_market?.return_5d)}>{formatPct(item.latest_market?.return_5d)}</b><small>完整EOD</small></span></td><td><RecentFive days={item.recent_5_trading_days} /></td><td><span className="two-line-cell holding-cell"><small>绝对 {item.strict_holding_interval?.status === "active" ? formatPct(item.strict_holding_interval.eod_return) : "—"}</small><small>广义 {item.broad_holding_interval?.status === "active" ? formatPct(item.broad_holding_interval.eod_return) : "—"}</small></span></td><td>{item.latest_market ? <span className="two-line-cell ma-cell"><small className={marketTone(item.latest_market.close_vs_ma5_pct)}>{maLine("MA5", item.latest_market.close_vs_ma5_pct)}</small><small className={marketTone(item.latest_market.close_vs_ma20_pct)}>{maLine("MA20", item.latest_market.close_vs_ma20_pct)}</small></span> : "—"}</td><td><IslandStatusBadge status={item.data_status} /></td></tr>)}</tbody></table></div>
  </div>;
}
