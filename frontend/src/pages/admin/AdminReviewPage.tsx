import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandDialog } from "../../components/island/IslandDialog";
import { IslandField } from "../../components/island/IslandField";
import { IslandSelect } from "../../components/island/IslandSelect";
import { IslandStatusBadge } from "../../components/island/IslandStatusBadge";
import type { Report, Sector } from "../../types";

export function AdminReviewPage() {
  const { reportId = "" } = useParams();
  const [report, setReport] = useState<Report | null>();
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [message, setMessage] = useState("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [termTargets, setTermTargets] = useState<Record<string, string>>({});

  useEffect(() => {
    api.adminReport(reportId).then(setReport).catch(() => setReport(null));
    api.sectors().then(setSectors).catch(() => setSectors([]));
  }, [reportId]);

  if (!report) return <p role="status">加载复核工作台…</p>;
  const refresh = (next: Report, text: string) => { setReport(next); setMessage(text); };

  return <div className="page">
    <header><IslandStatusBadge status={report.status} /><h1>报告复核</h1><p>{report.original_filename}</p></header>
    <div className="form-actions">
      <IslandButton onClick={() => api.parse(report.id).then(item => refresh(item, "本地解析完成，请人工复核"))}>本地解析</IslandButton>
      <IslandButton className="secondary" onClick={() => api.ready(report.id).then(item => refresh(item, "已标记待发布"))}>标记待发布</IslandButton>
      <IslandButton onClick={() => api.publish(report.id).then(item => refresh(item, "发布完成"))}>发布</IslandButton>
      <IslandButton className="secondary" onClick={() => setWithdrawOpen(true)}>撤回</IslandButton>
    </div>
    <p role="status">{message}</p>
    <div className="grid">
      <IslandCard title="结构化字段">
        <form className="stack" onSubmit={async event => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const next = await api.patch(report.id, {
            title: form.get("title"), report_date: form.get("date"), report_date_confirmed: true,
            core_view: form.get("core"), market_path: form.get("marketPath"), risk_warning: form.get("risk"),
            focus_sectors: String(form.get("focus") ?? "").split(/[，,、]/).map(item => item.trim()).filter(Boolean),
          });
          refresh(next, "复核内容已保存");
        }}>
          <IslandField label="报告标题" name="title" defaultValue={report.title} />
          <IslandField label="报告日期" name="date" type="date" defaultValue={report.report_date ?? report.candidate_report_date ?? ""} />
          <IslandField label="核心观点" name="core" multiline defaultValue={report.core_view} />
          <IslandField label="大盘路径" name="marketPath" multiline defaultValue={report.market_path} />
          <IslandField label="风险提示" name="risk" multiline defaultValue={report.risk_warning} />
          <IslandField label="重点板块（逗号分隔）" name="focus" defaultValue={report.focus_sectors.join("，")} />
          <IslandButton type="submit">保存并确认日期</IslandButton>
        </form>
      </IslandCard>
      <IslandCard title="原始提取文本"><pre style={{ whiteSpace: "pre-wrap" }}>{report.raw_text || "尚未解析"}</pre></IslandCard>
    </div>
    <IslandCard title="板块映射复核">
      <ul>{report.mentions.map(item => <li key={item.sector_key}>{item.sector_name}：{item.summary}</li>)}</ul>
      {report.unmapped_terms?.filter(item => item.status === "unresolved").map(item => <div className="form-actions" key={item.id}>
        <span>未映射：{item.term}</span>
        <IslandSelect label="绑定到既有板块" value={termTargets[item.id] ?? ""} options={sectors.map(sector => ({ value: sector.sector_key, label: sector.sector_name }))} onChange={value => setTermTargets(current => ({ ...current, [item.id]: value }))} />
        <IslandButton disabled={!termTargets[item.id]} onClick={async () => { await api.resolveTerm(item.id, termTargets[item.id]); refresh(await api.adminReport(report.id), "未映射词已绑定并记录审计"); }}>确认映射</IslandButton>
      </div>)}
    </IslandCard>
    <a href={report.pdf_url} target="_blank" rel="noreferrer">查看原始 PDF</a>
    <IslandDialog open={withdrawOpen} title="撤回已发布报告" onClose={() => setWithdrawOpen(false)}>
      <div className="stack"><IslandField label="撤回原因" multiline value={withdrawReason} onChange={event => setWithdrawReason(event.target.value)} /><IslandButton disabled={withdrawReason.trim().length < 3} onClick={() => api.withdraw(report.id, withdrawReason).then(item => { refresh(item, "报告已撤回"); setWithdrawOpen(false); })}>确认撤回</IslandButton></div>
    </IslandDialog>
  </div>;
}
