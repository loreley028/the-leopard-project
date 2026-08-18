import { useEffect, useRef } from "react";

export const MARKET_CURRENT_POLL_INTERVAL_MS = 5_000;
export type ReaderMarketSession = "morning_trading" | "afternoon_trading" | "lunch_break" | "after_close" | "pre_open" | "non_trading_day";

export const shouldPollMarketCurrent = (session: ReaderMarketSession | null | undefined) => (
  session === "morning_trading" || session === "afternoon_trading"
);

/** Poll only while a visible Reader page is in an active CN-A session.

 * Visibility restoration intentionally performs one immediate refresh.  The
 * backend remains the cache/single-flight boundary; this hook never polls a
 * hidden tab or any arbitrary symbol.
 */
export function useMarketCurrentPolling(
  refresh: () => Promise<{ session_state: ReaderMarketSession } | null>,
  enabled = true,
) {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!enabled || typeof document === "undefined") return;
    let disposed = false;
    let timer: number | undefined;
    const isVisible = () => document.visibilityState !== "hidden";
    const clear = () => { if (timer != null) window.clearTimeout(timer); timer = undefined; };
    const run = async () => {
      clear();
      if (disposed || !isVisible()) return;
      const result = await refreshRef.current().catch(() => null);
      if (!disposed && isVisible() && shouldPollMarketCurrent(result?.session_state)) {
        timer = window.setTimeout(() => { void run(); }, MARKET_CURRENT_POLL_INTERVAL_MS);
      }
    };
    const onVisibilityChange = () => { if (document.visibilityState === "visible") void run(); else clear(); };
    document.addEventListener("visibilitychange", onVisibilityChange);
    void run();
    return () => { disposed = true; clear(); document.removeEventListener("visibilitychange", onVisibilityChange); };
  }, [enabled]);
}
