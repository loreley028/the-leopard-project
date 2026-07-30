import { useEffect, useState } from "react";
import { useParams } from "../../routes/router";
import { api } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandDialog } from "../../components/island/IslandDialog";
import { IslandField } from "../../components/island/IslandField";
import { IslandSelect } from "../../components/island/IslandSelect";
import { IslandStatusBadge } from "../../components/island/IslandStatusBadge";
import { PdfPagePreview } from "../../components/PdfPagePreview";
import type { EnhancedReport, PathStatus, Report, Sector } from "../../types";

export function AdminReviewPage() {
  const { reportId = "" } = useParams();
  const [report, setReport] = useState<Report | null>();
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [message, setMessage] = useState("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [termTargets, setTermTargets] = useState<Record<string, string>>({});
  const [enhanced, setEnhanced] = useState<EnhancedReport | null>(null);
  const [previewLoaded, setPreviewLoaded] = useState(false);

  useEffect(() => {
    api.adminReport(reportId).then(setReport).catch(() => setReport(null));
    api.sectors().then(setSectors).catch(() => setSectors([]));
    api.enhancedReport(reportId).then(setEnhanced).catch(() => setEnhanced(null));
  }, [reportId]);

  if (!report) return <p role="status">加载复核工作台…</p>;
  const refresh = (next: Report, text: string) => { setReport(next); setMessage(text); };
  const refreshEnhanced = () => api.enhancedReport(report.id).then(setEnhanced);

  return <div className="page">
    <header><IslandStatusBadge status={report.status} /><h1>高级复核工作台</h1><p>{report.original_filename}</p><p className="muted">仅在自动解读存在异常时使用；普通流程请返回解读结果页。</p></header>
    <details className="advanced-review">
      <summary>重新解析与生命周期操作</summary>
      <div className="form-actions">
      <IslandButton onClick={() => api.parse(report.id).then(item => refresh(item, "本地解析完成，请人工复核"))}>本地解析</IslandButton>
      <IslandButton className="secondary" onClick={async () => { await api.enhanceParse(report.id); await refreshEnhanced(); setMessage("增强结构已生成：66个路径条目，外部LLM调用为0"); }}>增强解析</IslandButton>
      <IslandButton className="secondary" onClick={() => api.ready(report.id).then(item => refresh(item, "已标记待发布"))}>标记待发布</IslandButton>
      <IslandButton onClick={() => api.publish(report.id).then(item => refresh(item, "发布完成"))}>发布</IslandButton>
      <IslandButton className="secondary" onClick={async () => { await api.freezeMarketSnapshot(report.id); await refreshEnhanced(); setMessage("报告行情快照已固化；后续刷新不会覆盖"); }}>固化行情快照</IslandButton>
      <IslandButton className="secondary" onClick={() => setWithdrawOpen(true)}>撤回</IslandButton>
      </div>
    </details>
    <p role="status">{message}</p>
    <details className="advanced-review"><summary>手工调整报告字段和日期</summary><div className="grid">
      <IslandCard title="结构化字段">
        <form className="stack" onSubmit={async event => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const next = await api.patch(report.id, {
            title: form.get("title"), report_date: form.get("date"), report_date_confirmed: true,
            market_as_of_date: form.get("marketDate") || null, market_as_of_date_confirmed: Boolean(form.get("marketDate")),
            core_view: form.get("core"), market_path: form.get("marketPath"), risk_warning: form.get("risk"),
            focus_sectors: String(form.get("focus") ?? "").split(/[，,、]/).map(item => item.trim()).filter(Boolean),
          });
          refresh(next, "复核内容已保存");
        }}>
          <IslandField label="报告标题" name="title" defaultValue={report.title} />
          <IslandField label="报告日期" name="date" type="date" defaultValue={report.report_date ?? report.candidate_report_date ?? ""} />
          <IslandField label="行情截止日期（market_as_of_date，需管理员确认）" name="marketDate" type="date" defaultValue={report.market_as_of_date ?? report.candidate_market_as_of_date ?? ""} />
          <IslandField label="核心观点" name="core" multiline defaultValue={report.core_view} />
          <IslandField label="大盘路径" name="marketPath" multiline defaultValue={report.market_path} />
          <IslandField label="风险提示" name="risk" multiline defaultValue={report.risk_warning} />
          <IslandField label="重点板块（逗号分隔）" name="focus" defaultValue={report.focus_sectors.join("，")} />
          <IslandButton type="submit">保存并确认日期</IslandButton>
        </form>
      </IslandCard>
      <IslandCard title="原始提取文本"><pre style={{ whiteSpace: "pre-wrap" }}>{report.raw_text || "尚未解析"}</pre></IslandCard>
    </div></details>
    <details className="advanced-review"><summary>查看并编辑全部66个板块路径</summary><IslandCard title="历史路径矩阵复核（66个板块）">
      <p>未知状态会被后端拒绝；“未提”只表示当期没有明确提及。</p>
      <div className="admin-path-grid">{enhanced?.path_entries.map(entry => <label key={entry.id}>{entry.sector_name}<select value={entry.path_status} onChange={async event => { await api.patchPath(report.id, entry.id, { path_status: event.target.value as PathStatus, review_status: "confirmed" }); await refreshEnhanced(); }}><option value="avoid">不碰</option><option value="strong_watch">强观</option><option value="watch">观察</option><option value="weak_watch">弱观</option><option value="turn_hold">转持</option><option value="hold">持有</option><option value="turn_weak">转弱</option><option value="exit">离场</option><option value="not_mentioned">未提</option></select></label>)}</div>
    </IslandCard></details>
    <IslandCard title="板块详细解读复核">
      <div className="admin-assessment-list">{enhanced?.sector_assessments.filter(item => item.explicitly_mentioned).map(item => <details key={item.id}><summary>{item.sector_name} · {item.path_status_label}</summary><form className="stack" onSubmit={async event => { event.preventDefault(); const form = new FormData(event.currentTarget); await api.patchAssessment(report.id, item.id, { current_judgement: form.get("judgement"), main_basis: form.get("basis"), observation_condition: form.get("condition"), recent_path_summary: form.get("path"), review_status: "confirmed" }); await refreshEnhanced(); setMessage(`${item.sector_name}详细解读已保存并记录revision`); }}><IslandField label="历史路径（最近转折）" name="path" multiline defaultValue={item.recent_path_summary} /><IslandField label="当期判断" name="judgement" multiline defaultValue={item.current_judgement} /><IslandField label="主要依据" name="basis" multiline defaultValue={item.main_basis} /><IslandField label="观察条件" name="condition" multiline defaultValue={item.observation_condition} /><p className="muted">来源：{item.source_text_reference || "等待人工关联原文"}</p><IslandButton type="submit">保存该板块解读</IslandButton></form></details>)}</div>
    </IslandCard>
    <IslandCard title="板块映射复核">
      <p>已明确匹配的 {report.mentions.length} 个板块默认隐藏；这里只显示无法映射的异常项。</p>
      {report.unmapped_terms?.filter(item => item.status === "unresolved").map(item => <div className="form-actions" key={item.id}>
        <span>未映射：{item.term}</span>
        <IslandSelect label="绑定到既有板块" value={termTargets[item.id] ?? ""} options={sectors.map(sector => ({ value: sector.sector_key, label: sector.sector_name }))} onChange={value => setTermTargets(current => ({ ...current, [item.id]: value }))} />
        <IslandButton disabled={!termTargets[item.id]} onClick={async () => { await api.resolveTerm(item.id, termTargets[item.id]); refresh(await api.adminReport(report.id), "未映射词已绑定并记录审计"); }}>确认映射</IslandButton>
      </div>)}
    </IslandCard>
    <IslandCard title="原始PDF">
      {previewLoaded ? <PdfPagePreview reportId={report.id} /> : <IslandButton className="secondary" onClick={() => setPreviewLoaded(true)}>加载逐页预览</IslandButton>}
      <p><a href={report.pdf_download_url}>下载原始PDF</a></p>
    </IslandCard>
    <IslandDialog open={withdrawOpen} title="撤回已发布报告" onClose={() => setWithdrawOpen(false)}>
      <div className="stack"><IslandField label="撤回原因" multiline value={withdrawReason} onChange={event => setWithdrawReason(event.target.value)} /><IslandButton disabled={withdrawReason.trim().length < 3} onClick={() => api.withdraw(report.id, withdrawReason).then(item => { refresh(item, "报告已撤回"); setWithdrawOpen(false); })}>确认撤回</IslandButton></div>
    </IslandDialog>
  </div>;
}
