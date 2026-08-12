import { useState } from "react";
import { useNavigate, useSearchParams } from "../../routes/router";
import { api, ApiError } from "../../api/client";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandUploadZone } from "../../components/island/IslandUploadZone";

const STEPS = ["正在校验PDF", "正在读取报告", "正在识别日期和章节", "正在整理板块观点", "解读完成"];

export function AdminNewReportPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const selectedReportDate = params.get("report_date") ?? undefined;
  const [step, setStep] = useState(-1);
  const [message, setMessage] = useState("");
  const busy = step >= 0 && step < STEPS.length - 1;

  const upload = async (file: File) => {
    if (file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) {
      setMessage("请选择有效 PDF 文件");
      return;
    }
    setMessage("");
    setStep(0);
    const timers = [450, 900, 1350].map((delay, index) => window.setTimeout(() => setStep(index + 1), delay));
    try {
      const result = await api.interpret(file, selectedReportDate);
      timers.forEach(window.clearTimeout);
      setStep(4);
      if (result.publication === "published" || result.publication === "already_published") {
        setMessage(result.publication === "already_published" ? "该PDF已发布，正在打开正式报告" : "已通过严格校验并自动发布，正在打开正式报告");
        window.setTimeout(() => navigate(`/reports/${result.report.id}`), 250);
      } else {
        setMessage(result.duplicate ? "已识别为重复PDF，正在打开已有解读" : "存在需处理项，正在打开解读结果");
        window.setTimeout(() => navigate(`/admin/reports/${result.report.id}/interpretation`), 250);
      }
    } catch (error) {
      timers.forEach(window.clearTimeout);
      setStep(-1);
      setMessage(error instanceof ApiError ? error.message : "上传或解读失败，原始PDF不会被删除");
    }
  };

  return <div className="page interpretation-upload-page">
    <header>
      <p className="eyebrow">Phase 2A-0 · PDF主线</p>
      <h1>上传直播总结PDF</h1>
      {selectedReportDate && <p><strong>所选直播日期：</strong>{selectedReportDate}（PDF识别日期不一致时会阻止静默改写）</p>}
      <p>系统会在本机自动读取已有结构化PDF，识别日期、章节和板块观点，然后直接生成网页解读。</p>
    </header>
    <IslandCard>
      <IslandUploadZone onFile={upload} buttonLabel="上传并自动发布" disabled={busy} />
      {step >= 0 && <div className="interpretation-progress" aria-live="polite">
        <progress aria-label="解读进度" max={STEPS.length} value={step + 1} />
        <ol>{STEPS.map((label, index) => <li key={label} className={index <= step ? "complete" : ""} aria-current={index === step ? "step" : undefined}>{label}</li>)}</ol>
      </div>}
      <p role={message.includes("失败") || message.includes("有效") ? "alert" : "status"}>{message}</p>
      <p className="muted">PDF不会上传到第三方；不使用OCR或外部LLM。严格校验通过后自动发布；存在任何需人工处理项时不会发布。</p>
    </IslandCard>
  </div>;
}
