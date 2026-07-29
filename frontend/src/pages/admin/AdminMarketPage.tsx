import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { IslandButton } from "../../components/island/IslandButton";
import { IslandCard } from "../../components/island/IslandCard";
import type { IntradayStatus } from "../../types";
import { intradaySystemLabel } from "../../utils/intraday";

export function AdminMarketPage() {
  const [summary, setSummary] = useState<Record<string, unknown>>({});
  const [status, setStatus] = useState<Record<string, unknown>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [sectorKeys, setSectorKeys] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [importFile, setImportFile] = useState<File>();
  const [importPreview, setImportPreview] = useState<Record<string, unknown>>();
  const [intraday, setIntraday] = useState<IntradayStatus>();
  const [latestIntradayRun, setLatestIntradayRun] = useState<Record<string, unknown>>();
  const load = useCallback(async () => {
    const [nextSummary, nextStatus, nextIntraday, runs] = await Promise.all([api.marketSummary(), api.marketStatus(), api.intradayStatus(), api.marketRefreshRuns()]);
    setSummary(nextSummary); setStatus(nextStatus); setIntraday(nextIntraday); setAsOf(current => current || String(nextStatus.expected_latest_complete_trade_date ?? ""));
    const latest = runs.find(run => run.mode === "intraday_refresh");
    setLatestIntradayRun(latest?.run_id ? await api.marketRefreshRun(String(latest.run_id)) : undefined);
  }, []);
  useEffect(() => {
    let disposed = false; let timer = 0; let failures = 0;
    const poll = async () => { window.clearTimeout(timer); try { await load(); failures = 0; } catch { failures = Math.min(3, failures + 1); } finally { if (!disposed && document.visibilityState === "visible") timer = window.setTimeout(() => void poll(), Math.min(240_000, 45_000 * 2 ** failures)); } };
    const visible = () => { if (document.visibilityState === "visible") void poll(); else window.clearTimeout(timer); };
    document.addEventListener("visibilitychange", visible); void poll();
    return () => { disposed = true; window.clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [load]);
  const keys = sectorKeys.split(",").map(value => value.trim()).filter(Boolean);
  const refresh = async () => { setBusy(true); setMessage("正在以受控低速刷新真实研究行情…"); try { const result = await api.refreshRealMarket(asOf, keys.length ? keys : undefined); setMessage(`刷新完成：${String(result.success_count)}/${String(result.requested_count)}，失败${String(result.failure_count)}`); await load(); } catch (error) { setMessage(error instanceof ApiError ? error.message : "刷新失败"); } finally { setBusy(false); } };
  const previewImport = async () => { if (!importFile) return; setBusy(true); try { const result = await api.importMarket(importFile, false); setImportPreview(result); setMessage(`预览完成：可写入${String(result.ready_count ?? 0)}行`); } catch (error) { setMessage(error instanceof ApiError ? error.message : "预览失败"); } finally { setBusy(false); } };
  const confirmImport = async () => { if (!importFile) return; setBusy(true); try { const result = await api.importMarket(importFile, true); setMessage(`导入完成：成功${String(result.success_count ?? 0)}，失败${String(result.failure_count ?? 0)}`); setImportPreview(undefined); await load(); } catch (error) { setMessage(error instanceof ApiError ? error.message : "导入失败"); } finally { setBusy(false); } };
  const intradayAction = async (action: "start" | "pause" | "refresh") => { setBusy(true); try { const result = action === "start" ? await api.startIntraday() : action === "pause" ? await api.pauseIntraday() : await api.refreshIntradayNow(); setMessage(action === "start" ? "盘中刷新会话已启动；仅在受控交易时段请求。" : action === "pause" ? "盘中刷新会话已暂停。" : `立即刷新结果：${String((result as Record<string, unknown>).status ?? "完成")}`); await load(); } catch (error) { setMessage(error instanceof ApiError ? error.message : "盘中操作失败"); } finally { setBusy(false); } };
  return <div className="page"><header><p className="eyebrow">Admin · 行情运行状态</p><h1>行情数据</h1><p className="notice">研究辅助数据，无生产SLA。Viewer只读取服务器缓存；production_primary仍不存在。</p></header>
    <div className="dashboard-grid"><IslandCard title="当前Provider"><p><strong>{String(intraday?.provider ?? summary.provider ?? "尚未成功")}</strong></p><p>角色：{String(intraday?.provider_role ?? summary.provider_role ?? "research_provider")}</p><p>production_primary：不存在</p></IslandCard><IslandCard title="完整收盘数据"><p>预期完整日：{String(status.expected_latest_complete_trade_date ?? "—")}</p><p>最近成功日：{String(status.latest_complete_trade_date ?? status.latest_complete_eod ?? "尚无")}</p><p>缺失日期：{Array.isArray(status.missing_dates) && status.missing_dates.length ? status.missing_dates.join("、") : "无"}</p><p>失败Provider：{String(status.failed_provider ?? "无")}；最近重试：{String(status.last_retry_at ?? "—")}</p></IslandCard><IslandCard title="实时运行状态"><p>自动刷新：<strong>{intraday?.admin_paused ? "已暂停" : "运行中"}</strong></p><p>市场状态：<strong>{intradaySystemLabel(intraday)}</strong></p><p>实时覆盖：{intraday?.success_count ?? 0}/65</p><p>最近刷新/下次：{intraday?.latest_snapshot_at ?? "—"} / {intraday?.next_refresh_at ?? "—"}</p><p>Provider：{intraday?.provider ?? "research_intraday_chain"}</p></IslandCard></div>
    <IslandCard title="盘中行情缓存"><p>默认每{intraday?.refresh_interval_minutes ?? 5}分钟；real_local按安全配置启动一个统一调度器，65个支持板块统一刷新。Viewer只读缓存。</p><div className="form-actions"><IslandButton disabled={busy || !intraday?.admin_paused} onClick={() => void intradayAction("start")}>恢复刷新</IslandButton><IslandButton disabled={busy || Boolean(intraday?.admin_paused)} onClick={() => void intradayAction("pause")}>暂停</IslandButton><IslandButton disabled={busy || Boolean(intraday?.admin_paused) || intraday?.market_phase !== "intraday_open"} onClick={() => void intradayAction("refresh")}>立即刷新</IslandButton></div><p className="muted">午间休市、收盘后和非交易日属于市场自然停止，不会显示为管理员暂停，也不会请求Provider。</p></IslandCard>
    {latestIntradayRun && <IslandCard title="最近盘中 refresh run"><p><strong>{String(latestIntradayRun.run_id)}</strong></p><p>Provider：{String(latestIntradayRun.provider ?? intraday?.provider ?? "尚无")} · {String(latestIntradayRun.provider_role ?? "research_provider")}</p><p>成功/失败/延迟：{String(latestIntradayRun.success_count ?? 0)}/{String(latestIntradayRun.failure_count ?? 0)}/{String(latestIntradayRun.stale_count ?? 0)}；耗时：{latestIntradayRun.duration_ms == null ? "进行中" : `${String(latestIntradayRun.duration_ms)}ms`}</p><details><summary>查看板块结果与失败原因</summary><div className="refresh-result-list">{Array.isArray(latestIntradayRun.items) && latestIntradayRun.items.map((item: Record<string, unknown>) => <span key={String(item.sector_key)}><b>{String(item.sector_key)}</b><small>{String(item.status)}{item.provider_symbol ? ` · ${String(item.provider_symbol)}` : ""}{item.error_code ? ` · ${String(item.error_code)}` : ""}{item.error_message ? `：${String(item.error_message)}` : ""}</small></span>)}</div></details></IslandCard>}
    <IslandCard title="手工刷新真实研究行情"><label>截至日期<input type="date" value={asOf} onChange={event => setAsOf(event.target.value)} /></label><label>指定sector_key（逗号分隔，留空为65个）<input value={sectorKeys} onChange={event => setSectorKeys(event.target.value)} placeholder="bank,insurance" /></label><label className="confirm-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我确认使用公共诊断端点、串行低频请求，仅作研究辅助</label><IslandButton disabled={!confirmed || busy || !asOf} onClick={() => void refresh()}>{busy ? "处理中…" : keys.length ? "刷新指定板块" : "刷新65个受支持板块"}</IslandButton></IslandCard>
    <IslandCard title="CSV / Excel真实行情导入"><p>最低字段：trade_date、sector_key或sector_name、open、high、low、close、pre_close、volume；amount和turnover_rate可空。</p><input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={event => { setImportFile(event.target.files?.[0]); setImportPreview(undefined); }} /><div className="form-actions"><IslandButton disabled={!importFile || busy} onClick={() => void previewImport()}>预览导入</IslandButton><IslandButton disabled={!importFile || !importPreview || busy} onClick={() => void confirmImport()}>确认写入</IslandButton></div>{importPreview && <pre>{JSON.stringify(importPreview, null, 2)}</pre>}</IslandCard>
    <p role={message.includes("失败") ? "alert" : "status"}>{message}</p>
  </div>;
}
