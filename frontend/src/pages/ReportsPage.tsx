import { useEffect, useState } from "react";
import { Link } from "../routes/router";
import { api } from "../api/client";
import { IslandEmptyState } from "../components/island/IslandEmptyState";
import { IslandTable } from "../components/island/IslandTable";
import type { Report } from "../types";
import { formatShanghaiDateTime } from "../utils/format";
function weekLabel(value: string | null) { if (!value) return "待确认"; const day = new Date(`${value}T00:00:00+08:00`); const first = new Date(day.getFullYear(), 0, 1); return `${day.getFullYear()} · 第${Math.ceil((((day.getTime() - first.getTime()) / 86_400_000) + first.getDay() + 1) / 7)}周`; }
export function ReportsPage() { const [reports, setReports] = useState<Report[]>([]); useEffect(() => { api.reports().then(setReports).catch(() => setReports([])); }, []); if (!reports.length) return <IslandEmptyState title="暂无历史报告">周五、周六通常没有新报告，这是正常节奏。</IslandEmptyState>; return <div className="page"><h1>报告库</h1><p className="notice">仅展示已发布报告，按业务报告日期倒序；周五、周六无报告属于正常节奏。</p><IslandTable caption="已发布报告" headers={["周次", "报告日期", "行情截止日期", "标题", "重点板块数", "发布状态", "发布时间", "操作"]} rows={reports.map(item => [weekLabel(item.report_date), item.report_date, item.market_as_of_date ?? "未附加", item.title, item.focus_sectors.length, "已发布", item.published_at_display ?? formatShanghaiDateTime(item.published_at), <Link to={`/reports/${item.id}`} state={{ from: "library" }}>查看详细报告</Link>])} /></div>; }
