import { useCallback, useEffect, useState } from "react";
import { Link } from "../../routes/router";
import { api } from "../../api/client";
import { IslandCard } from "../../components/island/IslandCard";

type ReportDay = Awaited<ReturnType<typeof api.reportDays>>[number];
const STATE: Record<string, string> = {
  pending_upload: "待上传", normally_no_report: "通常无报告", skipped: "已跳过",
  needs_confirmation: "需要确认", published: "已发布", parsing: "正在解读",
};

function reportDayRange() {
  const now = new Date();
  const start = new Date(now); start.setDate(now.getDate() - 7);
  const end = new Date(now); end.setDate(now.getDate() + 7);
  const iso = (value: Date) => value.toISOString().slice(0, 10);
  return [iso(start), iso(end)] as const;
}

export function AdminDashboardPage() {
  const [days, setDays] = useState<ReportDay[]>([]);
  const [operations, setOperations] = useState<Awaited<ReturnType<typeof api.adminOperationsStatus>> | null>(null);
  const freshness = operations?.market_history_status;
  const load = useCallback(() => {
    const [start, end] = reportDayRange();
    return Promise.all([api.reportDays(start, end), api.adminOperationsStatus()]).then(([nextDays, nextOperations]) => {
      setDays(nextDays); setOperations(nextOperations);
    });
  }, []);
  useEffect(() => { void load(); }, [load]);
  const skip = async (day: string) => { await api.skipReportDay(day); await load(); };
  const cancel = async (day: string) => { await api.cancelReportDaySkip(day); await load(); };
  return <div className="page">
    <header><h1>管理区</h1><p>周日至周四默认待上传；周五、周六通常无报告，但可确认跳过或改为上传。</p><nav className="admin-primary-nav" aria-label="管理区功能"><Link to="/admin">每日报告</Link><Link to="/admin/market">行情数据</Link><Link to="/admin/specifications">制作规范备份</Link><Link to="/admin/reports">系统设置 / 版本历史</Link></nav></header>
    <IslandCard title="最近两周直播日程">
      <div className="table-wrap"><table><thead><tr><th>日期</th><th>星期</th><th>状态</th><th>文件 / 版本</th><th>操作</th></tr></thead><tbody>
        {days.map(day => <tr key={day.report_date}><td>{day.report_date}</td><td>{day.weekday}</td><td>{STATE[day.state] ?? day.state}</td><td>{day.reports[0] ? `${day.reports[0].original_filename ?? day.reports[0].title} · V${day.reports[0].revision_number ?? 1}` : "—"}</td><td><Link to={`/admin/reports/new?report_date=${day.report_date}`}>{day.state === "normally_no_report" || day.state === "skipped" ? "改为上传" : "上传PDF"}</Link>{" · "}{day.state === "skipped" ? <button type="button" onClick={() => void cancel(day.report_date)}>取消跳过</button> : <button type="button" onClick={() => void skip(day.report_date)}>确认跳过</button>}{day.reports[0] && <>{" · "}<Link to={`/admin/reports/${day.reports[0].id}/interpretation`}>查看解读</Link></>}</td></tr>)}
      </tbody></table></div>
    </IslandCard>
    <IslandCard title="每日运行状态">
      <div className="dashboard-grid compact-operation-status">
        <div><span>BUILD_COMMIT</span><strong>{operations?.build_commit ?? "读取中"}</strong></div>
        <div><span>DATA_SNAPSHOT_DATE</span><strong>{operations?.data_snapshot_date ?? "尚无数据快照"}</strong></div>
        <div><span>最新发布报告</span><strong>{operations?.latest_published_report_date ?? "暂无已发布报告"}</strong></div>
        <div><span>最新上证 EOD</span><strong>{operations?.latest_live_market_anchor_eod_date ?? "尚未采集"}</strong></div>
        <div><span>最新代理证券 EOD</span><strong>{operations?.latest_security_proxy_eod_date ?? "尚未采集"}</strong></div>
        <div><span>预期完整交易日</span><strong>{freshness?.expected_latest_completed ?? "读取中"}</strong></div>
        <div><span>Market Core</span><strong>{freshness?.market_core ? `${freshness.market_core.through_expected}/${freshness.market_core.required}` : "读取中"}</strong></div>
        <div><span>最近日终推进</span><strong>{freshness?.last_daily_advance ?? "尚无"}</strong></div>
        <div><span>最近协调 / 下次</span><strong>{freshness?.last_reconciliation ?? "尚无"} / {freshness?.next_scheduled?.at ?? "—"}</strong></div>
      </div>
      <p className="muted">{operations?.capture_schedule ?? "正在读取每日采集状态…"}</p>
      <button type="button" onClick={() => void load()}>重新检查状态</button>
    </IslandCard>
    <p><Link to="/admin/reports">查看全部版本历史</Link></p>
  </div>;
}
