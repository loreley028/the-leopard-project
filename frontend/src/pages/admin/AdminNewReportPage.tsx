import { useState } from "react";
import { useNavigate, useSearchParams } from "../../routes/router";
import { api, ApiError } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import { IslandUploadZone } from "../../components/island/IslandUploadZone";

const STEPS = ["正在校验PDF与MD", "正在核对报告日期和MD schema", "正在导入当天结构化观点", "正在写入增量路径与日历标记", "解读完成"];

interface MdPreview {
  reportDate: string;
  schema: string;
  schemaVersion: string;
  displayRowCount: number;
  activeObjectCount: number;
  updatedSectorCount: number;
  unmentionedSectorCount: number;
  validationStatus: string;
}

const scalar = (text: string, key: string) => text.match(new RegExp(`^${key}:\\s*["']?([^"'\\n]+)`, "m"))?.[1]?.trim() ?? "";
const fencedSection = (text: string, headingNumber: number) => text.match(new RegExp(`##\\s+${headingNumber}\\.[^\\n]*\\n\`\`\`yaml\\s*\\n([\\s\\S]*?)\\n\`\`\``, "i"))?.[1] ?? "";
const readText = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result ?? ""));
  reader.onerror = () => reject(reader.error);
  reader.readAsText(file, "utf-8");
});

function previewWebsiteMd(text: string): MdPreview {
  const activeObjectCount = Number(scalar(text, "active_object_count"));
  const updatedSectorCount = (fencedSection(text, 4).match(/^\s*-\s+sector:/gm) ?? []).length;
  const unmentionedSectorCount = (fencedSection(text, 5).match(/^\s*-\s+["']/gm) ?? []).length;
  const schema = scalar(text, "schema");
  const schemaVersion = scalar(text, "schema_version");
  const valid = schema === "leopard-website-md" && schemaVersion === "1.0" && updatedSectorCount + unmentionedSectorCount === activeObjectCount;
  return {
    reportDate: scalar(text, "report_date"),
    schema,
    schemaVersion,
    displayRowCount: Number(scalar(text, "display_row_count")),
    activeObjectCount,
    updatedSectorCount,
    unmentionedSectorCount,
    validationStatus: valid ? "客户端预检通过，等待服务端严格校验" : "客户端预检未通过",
  };
}

export function AdminNewReportPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const selectedReportDate = params.get("report_date") ?? undefined;
  const [pdfFile, setPdfFile] = useState<File>();
  const [mdFile, setMdFile] = useState<File>();
  const [mdPreview, setMdPreview] = useState<MdPreview>();
  const [step, setStep] = useState(-1);
  const [message, setMessage] = useState("");
  const busy = step >= 0 && step < STEPS.length - 1;

  const choosePdf = (file: File) => {
    if (file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) {
      setMessage("请选择有效 PDF 文件");
      setPdfFile(undefined);
      return;
    }
    setPdfFile(file);
    setMessage("");
  };

  const chooseMd = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".md")) {
      setMessage("请选择有效 MD 文件");
      setMdFile(undefined);
      setMdPreview(undefined);
      return;
    }
    setMdFile(file);
    setMessage("");
    try { setMdPreview(previewWebsiteMd(await readText(file))); }
    catch { setMdPreview(undefined); setMessage("无法读取 MD metadata"); }
  };

  const upload = async () => {
    if (!pdfFile || !mdFile || !mdPreview) {
      setMessage("请选择正式 PDF 和网站 MD");
      return;
    }
    if (mdPreview.validationStatus.includes("未通过")) {
      setMessage("MD 客户端预检未通过");
      return;
    }
    setMessage("");
    setStep(0);
    const timers = [450, 900, 1350].map((delay, index) => window.setTimeout(() => setStep(index + 1), delay));
    try {
      const result = await api.interpret(pdfFile, selectedReportDate, mdFile);
      timers.forEach(window.clearTimeout);
      setStep(4);
      if (result.publication === "published" || result.publication === "already_published") {
        setMessage(result.publication === "already_published" ? "该 PDF + MD 已发布，正在打开正式报告" : "PDF + MD 已通过严格校验并自动发布，正在打开正式报告");
        window.setTimeout(() => navigate(`/reports/${result.report.id}`), 250);
      } else {
        setMessage(result.duplicate ? "已识别为重复 PDF + MD，正在打开已有解读" : "存在需处理项，正在打开解读结果");
        window.setTimeout(() => navigate(`/admin/reports/${result.report.id}/interpretation`), 250);
      }
    } catch (error) {
      timers.forEach(window.clearTimeout);
      setStep(-1);
      setMessage(error instanceof ApiError ? error.message : "上传或导入失败，原始文件不会被删除");
    }
  };

  return <div className="page interpretation-upload-page">
    <header>
      <p className="eyebrow">结构化主线 · PDF + MD</p>
      <h1>上传直播总结</h1>
      {selectedReportDate && <p><strong>所选直播日期：</strong>{selectedReportDate}（PDF 与 MD 日期不一致时禁止发布）</p>}
      <p>PDF 用于展示、下载、留档与人工核验；网站 MD 是新报告结构化观点的主数据源。</p>
    </header>
    <IslandCard>
      <div className="dual-report-upload">
        <section><h2>正式 PDF</h2><IslandUploadZone onFile={choosePdf} buttonLabel="选择 PDF" disabled={busy} /><strong>{pdfFile ? "PDF：已选择" : "PDF：未选择"}</strong></section>
        <section><h2>网站 MD</h2><IslandUploadZone onFile={file => void chooseMd(file)} buttonLabel="选择 MD" acceptTypes="text/markdown,text/plain,.md" emptyLabel="拖放 MD 到这里，或使用键盘选择文件" disabled={busy} /><strong>{mdFile ? "MD：已选择" : "MD：未选择"}</strong></section>
      </div>
      {mdPreview && <dl className="md-metadata-preview" aria-label="MD metadata 预览">
        <div><dt>报告日期</dt><dd>{mdPreview.reportDate}</dd></div>
        <div><dt>schema</dt><dd>{mdPreview.schema}</dd></div>
        <div><dt>schema_version</dt><dd>{mdPreview.schemaVersion}</dd></div>
        <div><dt>display_row_count</dt><dd>{mdPreview.displayRowCount}</dd></div>
        <div><dt>active_object_count</dt><dd>{mdPreview.activeObjectCount}</dd></div>
        <div><dt>updated_sector_count</dt><dd>{mdPreview.updatedSectorCount}</dd></div>
        <div><dt>unmentioned_sector_count</dt><dd>{mdPreview.unmentionedSectorCount}</dd></div>
        <div><dt>validation status</dt><dd>{mdPreview.validationStatus}</dd></div>
      </dl>}
      <IslandButton disabled={busy || !pdfFile || !mdFile || !mdPreview} onClick={() => void upload()}>上传并自动发布</IslandButton>
      {step >= 0 && <div className="interpretation-progress" aria-live="polite">
        <progress aria-label="解读进度" max={STEPS.length} value={step + 1} />
        <ol>{STEPS.map((label, index) => <li key={label} className={index <= step ? "complete" : ""} aria-current={index === step ? "step" : undefined}>{label}</li>)}</ol>
      </div>}
      <p role={message.includes("失败") || message.includes("有效") || message.includes("未通过") ? "alert" : "status"}>{message}</p>
      <p className="muted">两份文件只在本机处理；MD 数量、schema、板块覆盖与 PDF 日期由服务端重新严格验证，不信任文件内 checks 声明。</p>
    </IslandCard>
  </div>;
}
