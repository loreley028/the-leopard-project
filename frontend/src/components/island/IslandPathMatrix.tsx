import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { PathMatrix, SectorResearch } from "../../types";
import { formatPct } from "../../utils/format";
import { IslandDialog } from "./IslandDialog";

type Cell = PathMatrix["rows"][number]["cells"][number] & { sector_name: string; sector_key: string };
const shortDate = (value: string) => value.slice(5).split("-").map(part => String(Number(part))).join("/");
const shortWeekday = (value: string | null) => (value ?? "").replace("周", "");

export function IslandPathMatrix({ matrix, period, onPeriodChange }: { matrix: PathMatrix; period: string; onPeriodChange: (value: string) => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState<Cell>();
  const [research, setResearch] = useState<SectorResearch | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const desktopGroups = useRef(new Map<string, HTMLTableRowElement>());
  const mobileGroups = useRef(new Map<string, HTMLElement>());
  useEffect(() => { if (viewport.current) viewport.current.scrollLeft = viewport.current.scrollWidth; }, [matrix]);
  useEffect(() => { setResearch(null); if (selected) void api.sectorResearch(selected.sector_key).then(setResearch).catch(() => setResearch(null)); }, [selected]);
  const reportIds = useMemo(() => new Set(matrix.dates.map(item => item.report_id)), [matrix.dates]);
  const groups = useMemo(() => {
    const rows = matrix.rows.filter(row => row.sector_name.includes(search.trim()) && (status === "all" || row.cells.some(cell => reportIds.has(cell.report_id) && cell.path_status === status)));
    const rowsByGroup = rows.reduce<Map<string, typeof rows>>((result, row) => { result.set(row.group_name, [...(result.get(row.group_name) ?? []), row]); return result; }, new Map());
    return matrix.groups
      .filter(item => rowsByGroup.has(item.group_name))
      .map(item => ({ ...item, rows: rowsByGroup.get(item.group_name) ?? [] }));
  }, [matrix.groups, matrix.rows, reportIds, search, status]);
  const [activeGroup, setActiveGroup] = useState(matrix.groups[0]?.group_name ?? "");
  useEffect(() => {
    if (!groups.some(item => item.group_name === activeGroup)) setActiveGroup(groups[0]?.group_name ?? "");
  }, [groups, activeGroup]);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(item => item.isIntersecting && (item.target as HTMLElement).offsetParent !== null)
        .sort((a, b) => Math.abs(a.boundingClientRect.top) - Math.abs(b.boundingClientRect.top));
      const name = (visible[0]?.target as HTMLElement | undefined)?.dataset.groupName;
      if (name) setActiveGroup(name);
    }, { rootMargin: "-140px 0px -65% 0px", threshold: [0, 1] });
    [...desktopGroups.current.values(), ...mobileGroups.current.values()].forEach(item => observer.observe(item));
    return () => observer.disconnect();
  }, [groups]);
  const jumpToGroup = (name: string) => {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    const target = (mobile ? mobileGroups : desktopGroups).current.get(name);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActiveGroup(name);
  };
  const selectedMarket = research?.history.find(item => item.report_id === selected?.detail_report_id)?.report_snapshot ?? null;
  const selectedHistory = research?.history.find(item => item.report_id === selected?.detail_report_id);
  return <div className="path-matrix-shell">
    <div className="matrix-controls" aria-label="历史路径筛选">
      <fieldset><legend>查看期数</legend>{["10", "20", "40", "all"].map(value => <button key={value} type="button" className={period === value ? "active" : ""} onClick={() => onPeriodChange(value)}>{value === "all" ? "全部" : `最近${value}期`}</button>)}</fieldset>
      <label>搜索板块<input value={search} onChange={event => setSearch(event.target.value)} placeholder="输入板块名称" /></label>
      <label>状态筛选<select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option>{matrix.status_contract.statuses.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
    </div>
    <nav className="group-jump-nav" aria-label="一级分组快捷导航">
      {groups.map(item => <button key={item.group_name} type="button" aria-current={activeGroup === item.group_name ? "true" : undefined} onClick={() => jumpToGroup(item.group_name)}>{item.group_name}<small>{item.rows.length}</small></button>)}
    </nav>
    <p className="matrix-caption">{matrix.caption}。主日期为直播报告日期；橙色小字为对应完整行情日期，周日报告通常关联上一个完整交易日。第二行仅为冻结EOD涨跌，盘中刷新不会改变这里。</p>
    <div className="matrix-desktop matrix-viewport" ref={viewport}>
      <table className="path-matrix"><caption className="sr-only">{matrix.caption}</caption><thead><tr><th className="sticky-sector" scope="col">板块</th>{matrix.dates.map((item, index) => <th className={index === matrix.dates.length - 1 ? "latest-column" : ""} scope="col" key={item.report_id} title={`直播报告 ${item.report_date} ${item.weekday}${item.market_as_of_date ? `；完整行情 ${item.market_as_of_date} ${item.market_weekday ?? ""}` : ""}`}><span>{shortDate(item.report_date)} <b>{shortWeekday(item.weekday)}</b></span>{item.market_as_of_date && item.market_as_of_date !== item.report_date && <small>行{shortDate(item.market_as_of_date)} {shortWeekday(item.market_weekday)}</small>}</th>)}</tr></thead>
        <tbody>{groups.flatMap(({ group_name: group, rows: items }) => [
          <tr className="matrix-group" data-group-name={group} ref={node => { if (node) desktopGroups.current.set(group, node); else desktopGroups.current.delete(group); }} key={`group-${group}`}><th className="sticky-sector matrix-group-label" scope="rowgroup">{group}</th><td colSpan={matrix.dates.length} aria-hidden="true" /></tr>,
          ...items.map(row => <tr key={row.sector_key}><th className="sticky-sector" scope="row"><Link to={`/sectors/${row.sector_key}`}>{row.sector_name}</Link></th>{row.cells.filter(cell => reportIds.has(cell.report_id)).map((cell, index) => <td key={cell.report_id} className={index === row.cells.filter(item => reportIds.has(item.report_id)).length - 1 ? "latest-column" : ""}><button type="button" className={`path-cell path-${cell.path_status}`} style={{ backgroundColor: cell.path_status_color }} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key })} aria-label={`${row.sector_name} ${cell.report_date} ${cell.path_status_label} ${cell.daily_return == null ? "—" : formatPct(cell.daily_return)}`}><span>{cell.path_status_label}</span><small>{cell.daily_return == null ? "—" : formatPct(cell.daily_return)}</small></button></td>)}</tr>),
        ])}</tbody>
      </table>
    </div>
    <div className="matrix-mobile" aria-label="移动端板块最近五期路径">{groups.map(({ group_name: group, rows: items }) => <section className="matrix-mobile-group" data-group-name={group} ref={node => { if (node) mobileGroups.current.set(group, node); else mobileGroups.current.delete(group); }} key={group}><h3>{group}</h3>{items.map(row => <details key={row.sector_key}><summary>{row.sector_name}</summary><ol>{row.cells.filter(cell => reportIds.has(cell.report_id)).slice(-5).map(cell => <li key={cell.report_id}><time>{cell.report_date}</time><button type="button" className={`path-chip path-${cell.path_status}`} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key })}>{cell.path_status_label}</button><span>{cell.judgement_summary || "本期未明确提及"}</span></li>)}</ol></details>)}</section>)}</div>
    <IslandDialog open={Boolean(selected)} title={selected ? `${selected.sector_name} · 报告${selected.report_date}` : "路径详情"} onClose={() => setSelected(undefined)}>
      {selected && <div className="stack"><p><strong>路径状态：</strong>{selected.path_status_label}</p><p><strong>报告日期：</strong>{selected.report_date}</p><p><strong>完整行情日期：</strong>{selected.market_as_of_date ?? "未附加"}；日涨跌 {formatPct(selected.daily_return)}</p>{selected.has_detailed_report ? <><p><strong>当期判断：</strong>{selectedHistory?.assessment.current_judgement || selected.judgement_summary || "本期未明确提及，不代表观点失效。"}</p><p><strong>主要依据：</strong>{selectedHistory?.assessment.main_basis || "—"}</p><p><strong>观察条件：</strong>{selectedHistory?.assessment.observation_condition || "—"}</p><p><strong>近5日：</strong>{formatPct(selectedMarket?.return_5d)}</p></> : <p className="notice">仅有路径记录，尚未补充该期原始报告。</p>}<p>{selected.detail_report_id && <><Link to={`/reports/${selected.detail_report_id}`}>来源报告</Link> · </>}<Link to={`/sectors/${selected.sector_key}`}>板块档案</Link></p></div>}
    </IslandDialog>
  </div>;
}
