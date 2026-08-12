import { useCallback, useEffect, useState } from "react";
import { api, ApiError, publicResourcePath } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";

export function AdminSpecificationsPage() {
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [file, setFile] = useState<File>();
  const [name, setName] = useState("大盘猎豹直播总结PDF制作规范");
  const [version, setVersion] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(() => api.specifications().then(setItems), []);
  useEffect(() => { void load(); }, [load]);
  const upload = async () => { if (!file || !version) return; try { const result = await api.uploadSpecification(file, name, version, effectiveDate, note); setMessage(result.duplicate ? "相同文件已存在，未重复创建" : "规范版本已归档，不会参与日报解析"); await load(); } catch (error) { setMessage(error instanceof ApiError ? error.message : "上传失败"); } };
  return <div className="page"><header><p className="eyebrow">Admin · 低频归档</p><h1>制作规范备份</h1><p>仅用于文件备份和版本管理，不参与日报解析，也不会影响日报上传。</p></header>
    <IslandCard title="上传新版本"><div className="specification-form"><label>规范名称<input value={name} onChange={event => setName(event.target.value)} /></label><label>版本号<input value={version} onChange={event => setVersion(event.target.value)} placeholder="V2.3.1" /></label><label>生效日期<input type="date" value={effectiveDate} onChange={event => setEffectiveDate(event.target.value)} /></label><label>备注<textarea value={note} onChange={event => setNote(event.target.value)} /></label><input type="file" accept=".pdf,.docx,.md,.txt" onChange={event => setFile(event.target.files?.[0])} /><IslandButton disabled={!file || !version} onClick={() => void upload()}>归档规范</IslandButton></div><p role="status">{message}</p></IslandCard>
    <IslandCard title={`历史版本 · ${items.length}`}><div className="table-wrap"><table><thead><tr><th>规范</th><th>版本</th><th>生效日期</th><th>文件</th><th>SHA-256</th><th>当前</th><th>操作</th></tr></thead><tbody>{items.map(item => <tr key={String(item.id)}><td>{String(item.specification_name)}</td><td>{String(item.version)}</td><td>{String(item.effective_date ?? "—")}</td><td>{String(item.original_filename)}</td><td><code>{String(item.sha256).slice(0, 12)}…</code></td><td>{item.is_current ? "是" : "否"}</td><td><a href={publicResourcePath(typeof item.file_url === "string" ? item.file_url : undefined)}>下载</a>{!item.is_current && <button type="button" onClick={async () => { await api.setCurrentSpecification(String(item.id)); await load(); }}>设为当前</button>}</td></tr>)}</tbody></table></div></IslandCard>
  </div>;
}
