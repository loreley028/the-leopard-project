import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "../../routes/router";
import { api, ApiError } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandField } from "../../components/island/IslandField";
import { PdfPagePreview } from "../../components/PdfPagePreview";
import type { Interpretation, Report, ReviewIssue } from "../../types";

const STATUS_LABELS: Record<string, string> = {
  avoid: "不碰", strong_watch: "强观", watch: "观察", weak_watch: "弱观",
  turn_hold: "转持", hold: "持有", turn_weak: "转弱", exit: "离场", not_mentioned: "未提",
};

const valueLabel = (value: unknown) => typeof value === "string" ? (STATUS_LABELS[value] ?? value) : String(value ?? "未识别");
const resolvedTime = (value: string | null) => value ? new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
}).format(new Date(value)) : "—";

function ReviewIssueCard({ issue, report, onSaved }: { issue: ReviewIssue; report: Report; onSaved: (result: { report: Report; interpretation: Interpretation }, message: string) => void }) {
  const [choice, setChoice] = useState(String(issue.final_value ?? issue.suggested_value ?? ""));
  const [busy, setBusy] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const save = async (finalValue: unknown, source: "accepted_suggestion" | "manual_override") => {
    setBusy(true);
    try {
      const result = await api.resolveReviewIssue(report.id, issue.issue_key, finalValue, source);
      onSaved(result, "已保存，本页剩余数量已更新");
    } finally { setBusy(false); }
  };
  return <article className={`review-issue-card ${issue.resolved ? "resolved" : issue.severity}`} aria-labelledby={`issue-${issue.issue_key}`}>
    <div className="review-issue-heading">
      <div><p className="eyebrow">{issue.subject_label}</p><h3 id={`issue-${issue.issue_key}`}>{issue.resolved ? "已处理" : issue.severity === "required" ? "需要您选择" : "建议检查"}</h3></div>
      <span className={`review-state review-state-${issue.resolved ? "resolved" : issue.severity}`}>{issue.resolved ? "已处理" : issue.severity === "required" ? "必须处理" : "有明确建议"}</span>
    </div>
    <p>{issue.explanation}</p>
    <dl className="review-decision-summary">
      <div><dt>系统识别</dt><dd>{valueLabel(issue.original_value)}</dd></div>
      <div><dt>{issue.resolved ? "最终采用" : "系统建议"}</dt><dd><strong>{valueLabel(issue.resolved ? issue.final_value : issue.suggested_value)}</strong></dd></div>
    </dl>
    {issue.resolved ? <div className="resolved-note"><strong>确认记录已保留</strong><span>{issue.resolution_source === "manual_override" ? "人工选择" : issue.resolution_source === "bulk_accept" ? "批量接受建议" : "接受系统建议"} · {resolvedTime(issue.resolved_at)} · {issue.resolved_by}</span>{report.status !== "published" && <button type="button" onClick={() => setChoice(String(issue.final_value ?? issue.suggested_value ?? ""))}>重新编辑</button>}</div> : <div className="review-actions">
      <IslandButton disabled={busy} onClick={() => void save(issue.suggested_value, "accepted_suggestion")}>接受“{valueLabel(issue.suggested_value)}”<small>建议</small></IslandButton>
      <label>改为<select value={choice} onChange={event => setChoice(event.target.value)}>{issue.options.map(option => <option key={option} value={option}>{valueLabel(option)}</option>)}</select></label>
      <IslandButton className="secondary" disabled={busy || choice === String(issue.suggested_value ?? "")} onClick={() => void save(choice, "manual_override")}>保存其他选择</IslandButton>
    </div>}
    <button className="evidence-toggle" type="button" aria-expanded={showEvidence} onClick={() => setShowEvidence(value => !value)}>{showEvidence ? "收起PDF原文" : "查看PDF原文"}</button>
    {showEvidence && <div className="review-evidence"><div><h4>PDF证据</h4><p>{issue.evidence.excerpt || "系统未能定位更具体的原文片段。"}</p><p className="muted">当前系统识别：{valueLabel(issue.original_value)}</p></div>{issue.evidence.page && <PdfPagePreview reportId={report.id} initialPage={issue.evidence.page} />}</div>}
    <details className="technical-details"><summary>查看技术详情</summary><dl><div><dt>页码</dt><dd>{issue.evidence.page ?? "未定位"}</dd></div><div><dt>解析方式</dt><dd>{issue.evidence.extraction_method ?? "本地规则"}</dd></div><div><dt>置信度</dt><dd>{issue.evidence.confidence ?? "未单列"}</dd></div><div><dt>异常代码</dt><dd>{issue.evidence.technical_codes?.join("、") || "无"}</dd></div></dl></details>
  </article>;
}

export function AdminInterpretationPage() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState<Report | null>(null);
  const [interpretation, setInterpretation] = useState<Interpretation | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [showBulkConfirm, setShowBulkConfirm] = useState(false);

  const applyResult = useCallback((result: { report: Report; interpretation: Interpretation }, nextMessage = "") => {
    setReport(result.report); setInterpretation(result.interpretation); setMessage(nextMessage);
  }, []);
  const load = useCallback(() => api.interpretation(reportId).then(result => applyResult(result)).catch(error => setMessage(error instanceof ApiError ? error.message : "无法读取解读结果")), [applyResult, reportId]);
  useEffect(() => { void load(); }, [load]);

  const groupedPaths = useMemo(() => {
    const groups = new Map<string, Interpretation["all_path_entries"]>();
    for (const item of interpretation?.all_path_entries ?? []) groups.set(item.group_name, [...(groups.get(item.group_name) ?? []), item]);
    return [...groups.entries()];
  }, [interpretation]);

  if (!report || !interpretation) return <p role="status">{message || "正在读取解读结果…"}</p>;
  const workflow = interpretation.review_workflow;
  const unresolved = workflow.issues.filter(item => !item.resolved);
  const resolved = workflow.issues.filter(item => item.resolved);
  const lowDate = interpretation.report_date_confidence === "low" && !interpretation.report_date_confirmed_by_user;

  const confirmDate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = new FormData(event.currentTarget); const reportDate = String(form.get("reportDate") ?? "");
    if (reportDate) applyResult(await api.patchInterpretation(report.id, { report_date: reportDate, report_date_confirmed: true }), "报告日期已确认");
  };
  const bulkAccept = async () => {
    setBusy(true); try { applyResult(await api.bulkAcceptReviewIssues(report.id), "系统建议已采用，人工选择未被修改"); setShowBulkConfirm(false); } finally { setBusy(false); }
  };
  const publish = async () => {
    setBusy(true); setMessage("");
    try { const published = await api.publish(report.id); navigate(`/reports/${published.id}`); }
    catch (error) { setMessage(error instanceof ApiError ? error.message : "发布失败"); setBusy(false); }
  };

  return <div className="page interpretation-result-page simple-review-flow">
    <ol className="review-stepper" aria-label="报告发布步骤">{workflow.steps.map((step, index) => <li key={step.key} className={step.state} aria-current={step.state === "current" ? "step" : undefined}><span>{index + 1}</span><strong>{step.label}</strong></li>)}</ol>
    <header className="report-header"><div><p className="eyebrow">报告解读</p><h1>解读完成</h1><h2>{report.title}</h2><div className="date-contract"><span>报告日期<strong>{report.report_date ?? "待确认"}</strong></span><span>当前状态<strong>{workflow.workflow_status === "published" ? "已发布" : workflow.workflow_status === "ready_to_publish" ? "可以发布" : workflow.workflow_status === "blocked" ? "需完成选择" : "待确认"}</strong></span></div><p className="muted">行情辅助数据缺失不影响确认与发布。</p></div></header>

    <section className="review-summary" aria-labelledby="review-summary-title"><h2 id="review-summary-title" className="sr-only">确认结果摘要</h2><div className="review-summary-card auto"><span>自动确认</span><strong>{workflow.summary.auto_confirmed}项</strong><small>系统已可靠完成</small></div><div className="review-summary-card suggestion"><span>建议检查</span><strong>{workflow.summary.suggested_review}项</strong><small>已有明确建议</small></div><div className="review-summary-card required"><span>必须处理</span><strong>{workflow.summary.must_handle}项</strong><small>需要您作出选择</small></div></section>

    <section className="review-primary-action" aria-live="polite">
      {workflow.workflow_status === "published" ? <><strong>全部疑问已处理，报告已发布</strong><Link to={`/reports/${report.id}`}>查看已发布报告</Link></> : workflow.summary.must_handle > 0 ? <><strong>还需处理 {workflow.summary.must_handle} 项</strong><a href="#review-issues">处理剩余问题</a></> : workflow.summary.suggested_review > 0 ? <><strong>系统已给出 {workflow.summary.suggested_review} 项建议</strong><IslandButton onClick={() => setShowBulkConfirm(true)}>接受全部系统建议</IslandButton><a href="#review-issues">逐项检查</a></> : <><strong>全部疑问已处理，报告可以发布</strong><IslandButton disabled={busy || lowDate} onClick={() => void publish()}>确认并发布</IslandButton></>}
    </section>
    {showBulkConfirm && <div className="bulk-confirm" role="dialog" aria-modal="true" aria-labelledby="bulk-confirm-title"><h2 id="bulk-confirm-title">接受全部系统建议？</h2><p>将采用系统建议处理 {workflow.summary.suggested_review} 项提醒，不会修改已确认项目。</p><div className="form-actions"><IslandButton disabled={busy} onClick={() => void bulkAccept()}>确认接受</IslandButton><IslandButton className="secondary" onClick={() => setShowBulkConfirm(false)}>返回</IslandButton></div></div>}

    {lowDate && <IslandCard title="需要确认报告日期"><form className="form-actions" onSubmit={confirmDate}><IslandField label="报告日期" name="reportDate" type="date" defaultValue={report.report_date ?? report.detected_report_date ?? ""} /><IslandButton type="submit">确认日期</IslandButton></form></IslandCard>}

    <section id="review-issues" aria-labelledby="review-issues-title"><div className="section-heading"><div><p className="eyebrow">第二步</p><h2 id="review-issues-title">检查少量疑问</h2></div><span>{unresolved.length ? `剩余 ${unresolved.length} 项` : "已全部处理"}</span></div>
      {unresolved.length ? <div className="review-issue-list">{unresolved.map(issue => <ReviewIssueCard key={issue.issue_key} issue={issue} report={report} onSaved={applyResult} />)}</div> : <p className="quality-success">当前没有未处理的问题。</p>}
      {resolved.length > 0 && <details className="resolved-issues" open><summary>已处理 {resolved.length} 项</summary><div className="review-issue-list">{resolved.map(issue => <ReviewIssueCard key={issue.issue_key} issue={issue} report={report} onSaved={applyResult} />)}</div></details>}
    </section>

    <details className="advanced-review"><summary>查看自动解读内容</summary><div className="dashboard-grid"><IslandCard title="核心观点"><p>{report.core_view}</p></IslandCard><IslandCard title="大盘路径"><p>{report.market_path}</p></IslandCard><IslandCard title="风险提示"><p>{report.risk_warning}</p></IslandCard><IslandCard title="重点板块"><div className="tag-list">{report.focus_sectors.map(item => <span key={item}>{item}</span>)}</div></IslandCard></div></details>
    <details className="advanced-review"><summary>查看全部66个板块路径</summary><div className="grouped-path-review">{groupedPaths.map(([group, items]) => <section key={group}><h3>{group}</h3><ul>{items.map(item => <li key={item.id}><span>{item.sector_name}</span><strong>{item.path_status_label}</strong></li>)}</ul></section>)}</div></details>
    <details className="advanced-review"><summary>高级技术信息</summary><p>以下内容仅用于少数恢复场景，不影响普通确认流程。</p><details><summary>原始提取文本</summary><pre className="raw-text-collapsed">{report.raw_text}</pre></details><details><summary>解析诊断</summary><pre>{JSON.stringify({ field_provenance: interpretation.field_provenance, quality_summary: interpretation.quality_summary, external_llm_calls: 0, ocr_used: false }, null, 2)}</pre></details><a href={report.pdf_download_url}>下载原始PDF</a></details>
    <p role={message.includes("失败") ? "alert" : "status"}>{message}</p>
  </div>;
}
