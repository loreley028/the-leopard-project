import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import type { Report } from "../types";
export function ReportDetailPage() { const { reportId = "" } = useParams(); const [report, setReport] = useState<Report | null>(); useEffect(() => { api.report(reportId).then(setReport).catch(() => setReport(null)); }, [reportId]); if (report === undefined) return <p role="status">加载报告…</p>; if (!report) return <p role="alert">未找到已发布报告。</p>; return <article className="page"><header><IslandStatusBadge status={report.status} /><h1>{report.title}</h1><p>{report.report_date}</p></header><div className="grid"><IslandCard title="核心观点"><p>{report.core_view}</p></IslandCard><IslandCard title="大盘路径"><p>{report.market_path}</p></IslandCard><IslandCard title="风险提示"><p>{report.risk_warning}</p></IslandCard></div><IslandCard title="结构化板块观点"><ul>{report.mentions.map(item => <li key={item.sector_key}><strong>{item.sector_name}</strong>：{item.summary}</li>)}</ul></IslandCard><a href={report.pdf_url} target="_blank" rel="noreferrer">打开或下载原始 PDF</a><p className="notice">{report.data_notice} 解析结果经管理员复核后发布。</p></article>; }
