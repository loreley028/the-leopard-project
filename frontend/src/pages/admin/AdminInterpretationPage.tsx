import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandField } from "../../components/island/IslandField";
import type { Interpretation, Report } from "../../types";
import { PdfPagePreview } from "../../components/PdfPagePreview";

const STATUS_LABELS: Record<string, string> = {
  avoid: "不碰", strong_watch: "强观", watch: "观察", weak_watch: "弱观",
  turn_hold: "转持", hold: "持有", turn_weak: "转弱", exit: "离场", not_mentioned: "未提",
};

const CONFIDENCE_LABELS = {
  high: "已自动识别",
  medium: "建议检查",
  low: "需要确认",
};

export function AdminInterpretationPage() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState<Report | null>(null);
  const [interpretation, setInterpretation] = useState<Interpretation | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [warningsConfirmed, setWarningsConfirmed] = useState(false);
  const [warningNote, setWarningNote] = useState("");

  const load = useCallback(() => api.interpretation(reportId).then(result => {
    setReport(result.report);
    setInterpretation(result.interpretation);
  }).catch(error => setMessage(error instanceof ApiError ? error.message : "无法读取解读结果")), [reportId]);

  useEffect(() => { void load(); }, [load]);

  const groupedPaths = useMemo(() => {
    const groups = new Map<string, Interpretation["all_path_entries"]>();
    for (const item of interpretation?.all_path_entries ?? []) {
      groups.set(item.group_name, [...(groups.get(item.group_name) ?? []), item]);
    }
    return [...groups.entries()];
  }, [interpretation]);

  if (!report || !interpretation) return <p role="status">{message || "正在读取解读结果…"}</p>;
  const lowDate = interpretation.report_date_confidence === "low" && !interpretation.report_date_confirmed_by_user;
  const blocking = interpretation.attention_items.filter(item => item.severity === "blocking");
  const warnings = interpretation.attention_items.filter(item => item.severity !== "blocking");
  const anomalies = interpretation.mentioned_assessments.filter(item => item.quality_status !== "verified_structure");

  const confirmDate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const reportDate = String(form.get("reportDate") ?? "");
    if (!reportDate) return;
    const result = await api.patchInterpretation(report.id, { report_date: reportDate, report_date_confirmed: true });
    setReport(result.report);
    setInterpretation(result.interpretation);
    setMessage("报告日期已确认");
  };

  const publish = async () => {
    setBusy(true);
    setMessage("");
    try {
      const published = await api.publish(report.id, warningsConfirmed, warningNote);
      navigate(`/reports/${published.id}`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "发布失败");
      setBusy(false);
    }
  };

  return <div className="page interpretation-result-page">
    <header className="report-header">
      <div>
        <p className="eyebrow">解读结果 · {interpretation.status === "needs_attention" ? "有少量内容需要确认" : "解读完成"}</p>
        <h1>{report.title}</h1>
        <div className="date-contract">
          <span>报告日期<strong>{report.report_date ?? "待确认"}</strong></span>
          <span>识别状态<strong>{CONFIDENCE_LABELS[interpretation.report_date_confidence]}</strong></span>
          <span>行情辅助数据<strong>{interpretation.market_data_status === "attached" ? "已附加" : "尚未绑定"}</strong></span>
        </div>
        {interpretation.report_date_confidence === "medium" && <p className="notice">报告日期识别为 {report.report_date}，请检查；不阻断查看。</p>}
      </div>
    </header>

    <section className={`quality-gate quality-${interpretation.quality_status}`} aria-labelledby="quality-gate-heading">
      <div><p className="eyebrow">发布质量闸门</p><h2 id="quality-gate-heading">{interpretation.quality_status === "verified_structure" ? "结构校验通过" : interpretation.quality_status === "blocking_parse_error" ? "存在阻塞级解析异常" : "存在需要复核的内容"}</h2><p>详细观点已恢复 {String(interpretation.quality_summary.assessment_rows ?? 0)} 条，历史矩阵 {String(interpretation.quality_summary.history_matrix_rows ?? interpretation.quality_summary.history_rows ?? 0)}/66 行，阻塞项 {blocking.length} 个。</p></div>
      <dl><div><dt>报告结构</dt><dd>{String(interpretation.quality_summary.report_structure ?? "待检查")}</dd></div><div><dt>历史矩阵</dt><dd>{String(interpretation.quality_summary.history_matrix ?? "待检查")}</dd></div><div><dt>可靠观点</dt><dd>{String(interpretation.quality_summary.assessment_verified ?? 0)}</dd></div></dl>
    </section>

    {lowDate && <IslandCard title="需要确认报告日期">
      <form className="form-actions" onSubmit={confirmDate}>
        <IslandField label="报告日期" name="reportDate" type="date" defaultValue={report.report_date ?? report.detected_report_date ?? ""} />
        <IslandButton type="submit">确认日期</IslandButton>
      </form>
    </IslandCard>}

    <section aria-labelledby="interpretation-overview">
      <h2 id="interpretation-overview">自动解读结果</h2>
      <div className="dashboard-grid">
        <IslandCard title="核心观点"><p>{report.core_view || "未可靠识别，已列入待确认项。"}</p></IslandCard>
        <IslandCard title="大盘路径"><p>{report.market_path || "未可靠识别，已列入待确认项。"}</p></IslandCard>
        <IslandCard title="风险提示"><p>{report.risk_warning || "本报告未单列风险提示。"}</p></IslandCard>
        <IslandCard title="重点板块"><div className="tag-list">{report.focus_sectors.length ? report.focus_sectors.map(item => <span key={item}>{item}</span>) : <span>本报告未单列重点板块</span>}</div></IslandCard>
      </div>
    </section>

    <section aria-labelledby="status-summary">
      <h2 id="status-summary">当期板块状态摘要</h2>
      <div className="status-distribution">{Object.entries(interpretation.status_counts).map(([status, count]) => <IslandCard key={status}><span className={`path-dot path-${status}`} aria-hidden="true" /><strong>{STATUS_LABELS[status]}</strong><b>{count}</b></IslandCard>)}</div>
    </section>

    <section aria-labelledby="mentioned-assessments">
      <h2 id="mentioned-assessments">原始PDF与解读结果核对</h2>
      <p className="muted">默认只列异常项；结构校验通过的板块收起在下方，避免重复人工检查。</p>
      <div className="pdf-review-split"><div className="pdf-preview">{previewLoaded ? <PdfPagePreview reportId={report.id} initialPage={anomalies[0]?.source_page ?? undefined} /> : <button type="button" onClick={() => setPreviewLoaded(true)}>加载PDF对照预览</button>}</div><div className="anomaly-review"><h3>需要处理的异常 · {anomalies.length}</h3>{anomalies.length ? anomalies.map(item => <IslandCard key={item.id}><div className="card-heading"><h4>{item.sector_name}</h4><strong>{item.path_status_label}</strong></div><p><b>问题：</b>{item.validation_flags?.join("、") || "结构需要人工确认"}</p><p><b>来源：</b>{item.source_page ? `第${item.source_page}页` : "页码待确认"} · {item.source_text_excerpt || item.source_text_reference}</p><p><Link to={`/admin/reports/${report.id}/review`}>进入修正工作台</Link></p></IslandCard>) : <p className="quality-success">全部详细观点均通过结构校验，无需逐项复核。</p>}</div></div>
    </section>

    <details className="advanced-review"><summary>查看已可靠恢复的 {interpretation.mentioned_assessments.length - anomalies.length} 条详细观点</summary><div className="assessment-list">{interpretation.mentioned_assessments.filter(item => item.quality_status === "verified_structure").map(item => <IslandCard key={item.id}><div className="card-heading"><h3>{item.sector_name}</h3><strong>{item.path_status_label}</strong></div><dl className="assessment-fields"><div><dt>历史路径</dt><dd>{item.recent_path_summary}</dd></div><div><dt>当期判断</dt><dd>{item.current_judgement}</dd></div><div><dt>主要依据</dt><dd>{item.main_basis}</dd></div><div><dt>观察条件</dt><dd>{item.observation_condition}</dd></div><div><dt>来源</dt><dd>{item.source_page ? `PDF第${item.source_page}页 · ` : ""}{item.source_text_excerpt}</dd></div></dl></IslandCard>)}</div></details>

    <aside aria-labelledby="attention-heading">
      <IslandCard title="待确认项">
        <h2 id="attention-heading" className="sr-only">待确认项</h2>
        {interpretation.attention_items.length ? <ul>{interpretation.attention_items.map((item, index) => <li key={`${item.kind}-${index}`}>{item.message}</li>)}</ul> : <p>没有需要人工处理的异常。</p>}
        <p className="muted">已明确匹配的 {interpretation.mapping_summary.confirmed ?? 0} 个板块不会重复列入复核清单。</p>
      </IslandCard>
    </aside>

    <details className="advanced-review">
      <summary>查看全部66个板块路径</summary>
      <div className="grouped-path-review">{groupedPaths.map(([group, items]) => <section key={group}><h3>{group}</h3><ul>{items.map(item => <li key={item.id}><span>{item.sector_name}</span><strong>{item.path_status_label}</strong></li>)}</ul></section>)}</div>
    </details>

    <details className="advanced-review">
      <summary>高级操作</summary>
      <div className="stack">
        <p>高级操作用于少数异常场景，普通发布流程不需要使用。</p>
        <div className="form-actions">
          <Link to={`/admin/reports/${report.id}/review`}>进入高级复核工作台</Link>
          <a href={report.pdf_download_url}>下载原始PDF</a>
        </div>
        <details><summary>查看原始提取文本</summary><pre className="raw-text-collapsed">{report.raw_text || "尚无原始文本"}</pre></details>
        <details><summary>查看解析诊断</summary><pre>{JSON.stringify({ field_provenance: interpretation.field_provenance, mapping_summary: interpretation.mapping_summary, external_llm_calls: 0, ocr_used: false }, null, 2)}</pre></details>
      </div>
    </details>

    <div className="interpretation-publish-bar">
      {warnings.length > 0 && <div className="warning-confirmation"><label><input type="checkbox" checked={warningsConfirmed} onChange={event => setWarningsConfirmed(event.target.checked)} />我已查看 {warnings.length} 项提醒，仍确认发布</label><input value={warningNote} onChange={event => setWarningNote(event.target.value)} placeholder="可选：确认说明" /></div>}
      <IslandButton className="secondary" onClick={() => setMessage("草稿已自动保存")}>保存草稿</IslandButton>
      <IslandButton disabled={busy || blocking.length > 0 || lowDate || (warnings.length > 0 && !warningsConfirmed)} onClick={publish}>确认并发布</IslandButton>
    </div>
    <p role={message.includes("失败") ? "alert" : "status"}>{message}</p>
  </div>;
}
