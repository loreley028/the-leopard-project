export type ReaderMarketSession = "morning_trading" | "lunch_break" | "afternoon_trading" | "after_close" | "pre_open" | "non_trading_day" | undefined;

const quoteTime = (quoteDatetime: string | null | undefined) => quoteDatetime?.slice(11, 16) || null;
const quoteDate = (quoteDatetime: string | null | undefined) => quoteDatetime ? quoteDatetime.slice(5, 10) : null;

/**
 * Reader-only label contract for a current quote.  The label is derived only
 * from the controlled CN-A session and the upstream quote timestamp; it never
 * substitutes the browser/server receive time for a market timestamp.
 */
export function marketSnapshotDisplayState(session: ReaderMarketSession, quoteDatetime?: string | null): string {
  const time = quoteTime(quoteDatetime);
  if (session === "morning_trading" || session === "afternoon_trading") return time ? `盘中 ${time}` : "盘中";
  if (session === "lunch_break") return time ? `午间 ${time}` : "午间";
  if (session === "after_close") return time ? `今日收盘 · ${time}` : "今日收盘";
  const date = quoteDate(quoteDatetime);
  return date ? `最近收盘 · ${date}` : "最近收盘";
}
