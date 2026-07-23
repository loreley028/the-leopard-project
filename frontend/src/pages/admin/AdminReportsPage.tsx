import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { IslandStatusBadge } from "../../components/island/IslandStatusBadge";
import { IslandTable } from "../../components/island/IslandTable";
import type { Report } from "../../types";
export function AdminReportsPage() { const [reports, setReports] = useState<Report[]>([]); useEffect(() => { api.adminReports().then(setReports); }, []); return <div className="page"><h1>全部报告</h1><IslandTable caption="草稿、已发布和已撤回报告" headers={["日期", "标题", "状态", "操作"]} rows={reports.map(item => [item.report_date ?? item.candidate_report_date ?? "待确认", item.title, <IslandStatusBadge status={item.status} />, <Link to={`/admin/reports/${item.id}/review`}>复核</Link>])} /></div>; }
