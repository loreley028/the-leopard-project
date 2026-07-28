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
  useEffect(() => { if (viewport.current) viewport.current.scrollLeft = viewport.current.scrollWidth; }, [matrix]);
  useEffect(() => { setResearch(null); if (selected) void api.sectorResearch(selected.sector_key).then(setResearch).catch(() => setResearch(null)); }, [selected]);
  const reportIds = useMemo(() => new Set(matrix.dates.map(item => item.report_id)), [matrix.dates]);
  const rows = matrix.rows.filter(row => row.sector_name.includes(search.trim()) && (status === "all" || row.cells.some(cell => reportIds.has(cell.report_id) && cell.path_status === status)));
  const groups = rows.reduce<Map<string, typeof rows>>((result, row) => { result.set(row.group_name, [...(result.get(row.group_name) ?? []), row]); return result; }, new Map());
  const selectedMarket = research?.history.find(item => item.report_id === selected?.detail_report_id)?.report_snapshot ?? null;
  const selectedHistory = research?.history.find(item => item.report_id === selected?.detail_report_id);
  return <div className="path-matrix-shell">
    <div className="matrix-controls" aria-label="历史路径筛选">
      <fieldset><legend>查看期数</legend>{["10", "20", "40", "all"].map(value => <button key={value} type="button" className={period === value ? "active" : ""} onClick={() => onPeriodChange(value)}>{value === "all" ? "全部" : `最近${value}期`}</button>)}</fieldset>
      <label>搜索板块<input value={search} onChange={event => setSearch(event.target.value)} placeholder="输入板块名称" /></label>
      <label>状态筛选<select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option>{matrix.status_contract.statuses.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
    </div>
    <p className="matrix-caption">{matrix.caption}。主日期为直播报告日期；橙色小字为对应完整行情日期，周日报告通常关联上一个完整交易日。第二行仅为冻结EOD涨跌，盘中刷新不会改变这里。</p>
    <div className="matrix-desktop matrix-viewport" ref={viewport}>
      <table className="path-matrix"><caption className="sr-only">{matrix.caption}</caption><thead><tr><th className="sticky-sector" scope="col">板块</th>{matrix.dates.map((item, index) => <th className={index === matrix.dates.length - 1 ? "latest-column" : ""} scope="col" key={item.report_id} title={`直播报告 ${item.report_date} ${item.weekday}${item.market_as_of_date ? `；完整行情 ${item.market_as_of_date} ${item.market_weekday ?? ""}` : ""}`}><span>{shortDate(item.report_date)} <b>{shortWeekday(item.weekday)}</b></span>{item.market_as_of_date && item.market_as_of_date !== item.report_date && <small>行{shortDate(item.market_as_of_date)} {shortWeekday(item.market_weekday)}</small>}</th>)}</tr></thead>
        <tbody>{Array.from(groups).flatMap(([group, items]) => [
          <tr className="matrix-group" key={`group-${group}`}><th colSpan={matrix.dates.length + 1}>{group}</th></tr>,
          ...items.map(row => <tr key={row.sector_key}><th className="sticky-sector" scope="row"><Link to={`/sectors/${row.sector_key}`}>{row.sector_name}</Link></th>{row.cells.filter(cell => reportIds.has(cell.report_id)).map((cell, index) => <td key={cell.report_id} className={index === row.cells.filter(item => reportIds.has(item.report_id)).length - 1 ? "latest-column" : ""}><button type="button" className={`path-cell path-${cell.path_status}`} style={{ backgroundColor: cell.path_status_color }} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key })} aria-label={`${row.sector_name} ${cell.report_date} ${cell.path_status_label} ${cell.daily_return == null ? "—" : formatPct(cell.daily_return)}`}><span>{cell.path_status_label}</span><small>{cell.daily_return == null ? "—" : formatPct(cell.daily_return)}</small></button></td>)}</tr>),
        ])}</tbody>
      </table>
    </div>
    <div className="matrix-mobile" aria-label="移动端板块最近五期路径">{rows.map(row => <details key={row.sector_key}><summary>{row.sector_name}</summary><ol>{row.cells.filter(cell => reportIds.has(cell.report_id)).slice(-5).map(cell => <li key={cell.report_id}><time>{cell.report_date}</time><button type="button" className={`path-chip path-${cell.path_status}`} onClick={() => setSelected({ ...cell, sector_name: row.sector_name, sector_key: row.sector_key })}>{cell.path_status_label}</button><span>{cell.judgement_summary || "本期未明确提及"}</span></li>)}</ol></details>)}</div>
    <IslandDialog open={Boolean(selected)} title={selected ? `${selected.sector_name} · 报告${selected.report_date}` : "路径详情"} onClose={() => setSelected(undefined)}>
      {selected && <div className="stack"><p><strong>路径状态：</strong>{selected.path_status_label}</p><p><strong>报告日期：</strong>{selected.report_date}</p><p><strong>完整行情日期：</strong>{selected.market_as_of_date ?? "未附加"}；日涨跌 {formatPct(selected.daily_return)}</p>{selected.has_detailed_report ? <><p><strong>当期判断：</strong>{selectedHistory?.assessment.current_judgement || selected.judgement_summary || "本期未明确提及，不代表观点失效。"}</p><p><strong>主要依据：</strong>{selectedHistory?.assessment.main_basis || "—"}</p><p><strong>观察条件：</strong>{selectedHistory?.assessment.observation_condition || "—"}</p><p><strong>近5日：</strong>{formatPct(selectedMarket?.return_5d)}</p></> : <p className="notice">仅有路径记录，尚未补充该期原始报告。</p>}<p>{selected.detail_report_id && <><Link to={`/reports/${selected.detail_report_id}`}>来源报告</Link> · </>}<Link to={`/sectors/${selected.sector_key}`}>板块档案</Link></p></div>}
    </IslandDialog>
  </div>;
}
