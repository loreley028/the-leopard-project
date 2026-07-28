import type { IntradayStatus, Sector } from "../types";
import { formatPct } from "./format";

export interface RealtimePresentation {
  value: string;
  detail?: string;
  tone: "up" | "down" | "flat";
}

const tone = (value: number | null | undefined): RealtimePresentation["tone"] => value == null || value === 0 ? "flat" : value > 0 ? "up" : "down";
export const timeOnly = (value: string | null | undefined) => value?.match(/(\d{2}:\d{2})(?::\d{2})?$/)?.[1] ?? "—";

export function realtimePresentation(item: Sector, system?: IntradayStatus): RealtimePresentation {
  const snapshot = item.intraday_snapshot;
  const sameTradeDate = Boolean(snapshot && system?.intraday_trade_date && snapshot.trade_date === system.intraday_trade_date);
  if (system?.market_phase === "market_closed" && system.market_phase_detail === "non_trading_day") return { value: "休市", tone: "flat" };
  if (system?.market_phase === "market_closed" && system.market_phase_detail === "after_close") {
    const complete = item.latest_market && item.latest_market.trade_date === system.intraday_trade_date;
    return complete ? { value: formatPct(item.latest_market?.daily_pct_change), detail: "今日收盘", tone: tone(item.latest_market?.daily_pct_change) } : { value: "暂无实时", detail: "等待收盘数据", tone: "flat" };
  }
  if (system?.market_phase === "market_break") {
    return sameTradeDate ? { value: formatPct(snapshot?.pct_change), detail: "午间休市", tone: tone(snapshot?.pct_change) } : { value: "暂无实时", detail: "午间休市", tone: "flat" };
  }
  if (item.intraday_status === "intraday_fresh" && sameTradeDate && snapshot) return { value: formatPct(snapshot.pct_change), detail: timeOnly(snapshot.observed_at), tone: tone(snapshot.pct_change) };
  return { value: "暂无实时", tone: "flat" };
}

export function intradaySystemLabel(status?: IntradayStatus): string {
  if (!status) return "状态读取中";
  if (status.market_phase === "market_break") return "午间休市";
  if (status.market_phase === "market_closed") return status.market_phase_detail === "after_close" ? "已收盘" : "休市";
  if (status.failure_count > 0 && !status.latest_snapshot_at) return "盘中行情获取失败";
  if (status.stale_count > 0) return "盘中数据延迟";
  return status.session_status === "running" ? "运行中" : "已暂停";
}

export function intradayDataLabel(dataStatus: string | undefined, system?: IntradayStatus): string {
  if (dataStatus === "provider_failed") return "获取失败";
  if (dataStatus === "market_break") return "午间休市";
  if (dataStatus === "market_closed") return system?.market_phase_detail === "after_close" ? "已收盘" : "休市";
  if (dataStatus === "intraday_stale") return "数据延迟";
  if (dataStatus === "unsupported") return "暂不支持";
  return "暂无快照";
}
