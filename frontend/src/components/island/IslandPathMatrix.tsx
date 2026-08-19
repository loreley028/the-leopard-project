import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "../../routes/router";
import { api } from "../../api/client";
import type { PathMatrix, SectorResearch } from "../../types";
import { formatPct } from "../../utils/format";
import { IslandDialog } from "./IslandDialog";

type Cell = PathMatrix["rows"][number]["cells"][number] & { sector_name: string; sector_key: string; market_available?: boolean };
const shortDate = (value: string) => value.slice(5).split("-").map(part => String(Number(part))).join("/");
const shortWeekday = (value: string | null) => (value ?? "").replace("周", "");
const marketOverlayLabel = (cell: Cell) => cell.market_overlay?.label ?? (cell.daily_return == null ? "—" : formatPct(cell.daily_return));
const marketOverlayTitle = (cell: Cell) => {
  const overlay = cell.market_overlay;
  if (!overlay || overlay.kind === "unavailable") return "该交易日暂无可用客观行情";
  return `${overlay.market_date ?? "该交易日"}固定主观察标的；点击查看相关证券逐项表现。`;
};
const reportStatus = (cell: Cell) => cell.report_present ? cell.path_status_label ?? "—" : "";
const cellAriaLabel = (sectorName: string, cell: Cell) => `${sectorName} 行情 ${cell.trading_date} ${cell.report_present ? `报告 ${cell.report_date} ${reportStatus(cell)}` : "该交易日无对应报告观点"} ${marketOverlayLabel(cell)}`;

export function IslandPathMatrix({ matrix, period, onPeriodChange }: { matrix: PathMatrix; period: string; onPeriodChange: (value: string) => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [showDormant, setShowDormant] = useState(false);
  const [selected, setSelected] = useState<Cell>();
  const [research, setResearch] = useState<SectorResearch | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const desktopGroups = useRef(new Map<string, HTMLTableRowElement>());
  const mobileGroups = useRef(new Map<string, HTMLElement>());
  useEffect(() => { if (viewport.current) viewport.current.scrollLeft = viewport.current.scrollWidth; }, [matrix]);
  useEffect(() => {
    setResearch(null);
    if (selected?.detail_report_id) void api.sectorResearch(selected.sector_key).then(setResearch).catch(() => setResearch(null));
  }, [selected]);
  const groups = useMemo(() => {
    const rows = matrix.rows.filter(row => row.sector_name.includes(search.trim()) && (showDormant || !row.is_dormant_20d || Boolean(search.trim())) && (status === "all" || row.cells.some(cell => cell.path_status === status)));
    const rowsByGroup = rows.reduce<Map<string, typeof rows>>((result, row) => { result.set(row.group_name, [...(result.get(row.group_name) ?? []), row]); return result; }, new Map());
    return matrix.groups.filter(item => rowsByGroup.has(item.group_name)).map(item => ({ ...item, rows: rowsByGroup.get(item.group_name) ?? [] }));
  }, [matrix.groups, matrix.rows, search, status, showDormant]);
  const [activeGroup, setActiveGroup] = useState(matrix.groups[0]?.group_name ?? "");
  useEffect(() => { if (!groups.some(item => item.group_name === activeGroup)) setActiveGroup(groups[0]?.group_name ?? ""); }, [groups, activeGroup]);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(item => item.isIntersecting && (item.target as HTMLElement).offsetParent !== null).sort((a, b) => Math.abs(a.boundingClientRect.top) - Math.abs(b.boundingClientRect.top));
      const name = (visible[0]?.target as HTMLElement | undefined)?.dataset.groupName;
      if (name) setActiveGroup(name);
    }, { rootMargin: "-140px 0px -65% 0px", threshold: [0, 1] });
    [...desktopGroups.current.values(), ...mobileGroups.current.values()].forEach(item => observer.observe(item));
    return () => observer.disconnect();
  }, [groups]);
  const jumpToGroup = (name: string) => {
    const target = (window.matchMedia("(max-width: 760px)").matches ? mobileGroups : desktopGroups).current.get(name);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActiveGroup(name);
  };
  const selectedHistory = selected?.detail_report_id ? research?.history.find(item => item.report_id === selected.detail_report_id) : undefined;
  return <div className="path-matrix-shell">
    <div className="matrix-controls" aria-label="历史路径筛选">
      <fieldset><legend>查看交易日</legend>{["10", "20", "40", "all"].map(value => <button key={value} type="button" className={period === value ? "active" : ""} onClick={() => onPeriodChange(value)}>{value === "all" ? "全部" : `最近${value}个交易日`}</button>)}</fieldset>
      <label>搜索板块<input value={search} onChange={event => setSearch(event.target.value)} placeholder="输入板块名称" /></label>
      <label>状态筛选<select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option>{matrix.status_contract.statuses.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
      <label className="matrix-dormant-toggle"><input type="checkbox" checked={showDormant} onChange={event => setShowDormant(event.target.checked)} /> 显示20日未提板块{matrix.rows.some(row => row.is_dormant_20d) ? `（${matrix.rows.filter(row => row.is_dormant_20d).length}）` : ""}</label>
    </div>
    <nav className="group-jump-nav" aria-label="一级分组快捷导航">{groups.map(item => <button key={item.group_name} type="button" aria-current={activeGroup === item.group_name ? "true" : undefined} onClick={() => jumpToGroup(item.group_name)}>{item.group_name}<small>{item.rows.length}</small></button>)}</nav>
    <p className="matrix-caption">{matrix.caption}按受控完整交易日排列；颜色为当期报告路径标记，“未提”表示该期未单独更新。市场行情仅按该日期精确读取，不做行情数据回退。相关证券逐项表现请点击查看；不构成板块指数或综合收益。</p>
    <div className="matrix-desktop matrix-viewport" ref={viewport}>
      <table className="path-matrix" data-column-model="fixed"><colgroup><col className="matrix-sector-column" />{matrix.dates.map(item => <col className="matrix-date-column" key={item.trading_date} />)}</colgroup><caption className="sr-only">{matrix.caption}</caption><thead><tr><th className="sticky-sector" scope="col">板块</th>{matrix.dates.map((item, index) => <th className={index === matrix.dates.length - 1 ? "latest-column" : ""} scope="col" key={item.trading_date} title={`完整交易日 ${item.trading_date} ${item.weekday}`}><span className="matrix-date-header">{shortDate(item.trading_date)} <b>{shortWeekday(item.weekday)}</b></span></th>)}</tr></thead>
        <tbody>{groups.flatMap(({ group_name: group, rows: items }) => [
          <tr className="matrix-group" data-group-name={group} ref={node => { if (node) desktopGroups.current.set(group, node); else desktopGroups.current.delete(group); }} key={`group-${group}`}><th className="sticky-sector matrix-group-label" scope="rowgroup">{group}</th><td colSpan={matrix.dates.length} aria-hidden="true" /></tr>,
          ...items.map(row => <tr key={row.sector_key}><th className="sticky-sector" scope="row">{row.market_available === false ? <span>{row.sector_name}</span> : <Link to={`/sectors/${row.sector_key}`}>{row.sector_name}</Link>}</th>{row.cells.map((cell, index) => <td key={cell.trading_date} className={index === row.cells.length - 1 ? "latest-column" : ""}><button type="button" className={`path-cell ${cell.path_status ? `path-${cell.path_status}` : "path-no-report"}`} style={cell.path_status_color ? { backgroundColor: cell.path_status_color } : undefined} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key, market_available: row.market_available })} aria-label={cellAriaLabel(row.sector_name, cell)} title={marketOverlayTitle(cell)}><span>{reportStatus(cell)}</span><small className={`market-overlay-${cell.market_overlay?.kind ?? "unavailable"}`}>{marketOverlayLabel(cell)}</small></button></td>)}</tr>),
        ])}</tbody>
      </table>
    </div>
    <div className="matrix-mobile" aria-label="移动端板块最近五个交易日行情">{groups.map(({ group_name: group, rows: items }) => <section className="matrix-mobile-group" data-group-name={group} ref={node => { if (node) mobileGroups.current.set(group, node); else mobileGroups.current.delete(group); }} key={group}><h3>{group}</h3>{items.map(row => <details key={row.sector_key}><summary>{row.sector_name}</summary><ol>{row.cells.slice(-5).map(cell => <li key={cell.trading_date}><time>{cell.trading_date}</time>{cell.report_present ? <button type="button" className={`path-chip path-${cell.path_status}`} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key })}>{reportStatus(cell)}</button> : <span className="matrix-no-report">无报告观点</span>}<span><small>{marketOverlayLabel(cell)}</small></span></li>)}</ol></details>)}</section>)}</div>
    <IslandDialog open={Boolean(selected)} title={selected ? `${selected.sector_name} · 行情 ${selected.trading_date}` : "路径详情"} onClose={() => setSelected(undefined)}>
      {selected && <div className="stack matrix-dialog-content">{selected.report_present ? <p><strong>报告观点：</strong>{reportStatus(selected)}<br /><small>报告日期：{selected.report_date}</small></p> : <p className="muted">该交易日无对应报告观点。</p>}{selected.market_overlay?.kind === "unavailable" && <p className="notice">该交易日暂无可靠主观察标的行情。</p>}{selected.market_overlay?.kind === "primary" && <section className="matrix-market-detail"><strong>主观察标的</strong>{selected.market_overlay.primary && <div className="matrix-primary-observation"><span>{selected.market_overlay.primary.name} · {selected.market_overlay.primary.security_code}</span><small>{selected.market_overlay.primary.role === "etf" ? "代理ETF" : "核心公司"}</small><b>收盘 {selected.market_overlay.primary.close.toFixed(2)} · {formatPct(selected.market_overlay.primary.pct_change)}</b></div>}{selected.market_overlay.instruments.length > 0 && <><strong className="matrix-related-heading">相关证券</strong><ul>{selected.market_overlay.instruments.map(item => <li key={`${item.name}-${item.trading_date}`}><span>{item.name} · {item.security_code}<small>{item.role === "etf" ? "代理ETF" : "核心公司"}</small></span><span>收盘 {item.close.toFixed(2)} · {formatPct(item.pct_change)}</span></li>)}</ul></>}<p className="matrix-disclosure">以下为相关证券逐项表现，不代表板块指数或综合收益。</p></section>}{selected.has_detailed_report ? <><p><strong>报告依据：</strong>{selectedHistory?.assessment.main_basis || "—"}</p><p><strong>观察条件：</strong>{selectedHistory?.assessment.observation_condition || "—"}</p></> : selected.report_present ? <p className="muted">该日为历史路径记录，无独立报告正文。</p> : null}<p>{selected.detail_report_id && <><Link to={`/reports/${selected.detail_report_id}`}>来源报告</Link>{selected.market_available !== false && " · "}</>}{selected.market_available !== false && <Link to={`/sectors/${selected.sector_key}`}>板块档案</Link>}</p></div>}
    </IslandDialog>
  </div>;
}
