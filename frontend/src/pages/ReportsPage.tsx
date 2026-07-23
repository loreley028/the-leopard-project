import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { IslandEmptyState } from "../components/island/IslandEmptyState";
import { IslandTable } from "../components/island/IslandTable";
import type { Report } from "../types";
function weekLabel(value: string | null) { if (!value) return "待确认"; const day = new Date(`${value}T00:00:00+08:00`); const first = new Date(day.getFullYear(), 0, 1); return `${day.getFullYear()} · 第${Math.ceil((((day.getTime() - first.getTime()) / 86_400_000) + first.getDay() + 1) / 7)}周`; }
export function ReportsPage() { const [reports, setReports] = useState<Report[]>([]); useEffect(() => { api.reports().then(setReports).catch(() => setReports([])); }, []); if (!reports.length) return <IslandEmptyState title="暂无历史报告">周五、周六通常没有新报告，这是正常节奏。</IslandEmptyState>; return <div className="page"><h1>历史报告</h1><p className="notice">按报告日期倒序并标注周次。周五、周六无报告不会标记为缺失。</p><IslandTable caption="已发布报告" headers={["周次", "报告日期", "标题", "发布时间", "操作"]} rows={reports.map(item => [weekLabel(item.report_date), item.report_date, item.title, item.published_at, <Link to={`/reports/${item.id}`}>查看</Link>])} /></div>; }
