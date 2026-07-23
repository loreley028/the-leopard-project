import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandEmptyState } from "../components/island/IslandEmptyState";
import { IslandTag } from "../components/island/IslandTag";
import type { Report } from "../types";
export function HomePage() { const [report, setReport] = useState<Report | null>(); useEffect(() => { api.latestReport().then(setReport).catch(() => setReport(null)); }, []); if (report === undefined) return <p role="status">正在打开公告板…</p>; if (!report) return <IslandEmptyState title="岛上还没有已发布报告">管理员完成上传、复核和发布后，最新研究会出现在这里。</IslandEmptyState>; return <div className="page"><section className="hero"><div><p className="eyebrow">最新已发布 · {report.report_date}</p><h1>{report.title}</h1><p>{report.core_view}</p><div className="form-actions">{report.focus_sectors.map(item => <IslandTag key={item}>{item}</IslandTag>)}</div><p><Link to={`/reports/${report.id}`}>进入本期报告 →</Link></p></div><div className="hero-island" aria-label="原创岛屿研究插画装饰" role="img" /></section><div className="grid"><IslandCard title="大盘路径"><p>{report.market_path || "本期未明确提取，等待复核。"}</p></IslandCard><IslandCard title="客观变化摘要"><p>{report.change_summary?.text ?? "暂无可比较的已发布报告。"}</p></IslandCard><IslandCard title="数据状态"><p>{report.data_notice}</p><p className="muted">上传：{report.created_at}<br />发布：{report.published_at}</p></IslandCard></div></div>; }
