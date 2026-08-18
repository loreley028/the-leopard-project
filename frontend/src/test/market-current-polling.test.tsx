import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MARKET_CURRENT_POLL_INTERVAL_MS, useMarketCurrentPolling } from "../hooks/useMarketCurrentPolling";

function Harness({ refresh }: { refresh: () => Promise<{ session_state: "morning_trading" | "afternoon_trading" | "lunch_break" } | null> }) {
  useMarketCurrentPolling(refresh);
  return null;
}

describe("market current polling", () => {
  it("polls every five seconds only while the document is visible and the session is active", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn().mockResolvedValue({ session_state: "afternoon_trading" as const });
    const visibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    const view = render(<Harness refresh={refresh} />);
    await act(async () => { await Promise.resolve(); });
    expect(refresh).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(MARKET_CURRENT_POLL_INTERVAL_MS); });
    expect(refresh).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(MARKET_CURRENT_POLL_INTERVAL_MS * 2); });
    expect(refresh).toHaveBeenCalledTimes(2);
    view.unmount();
    if (visibility) Object.defineProperty(document, "visibilityState", visibility); else delete (document as { visibilityState?: string }).visibilityState;
    vi.useRealTimers();
  });

  it("does not schedule another request during lunch", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn().mockResolvedValue({ session_state: "lunch_break" as const });
    const view = render(<Harness refresh={refresh} />);
    await act(async () => { await Promise.resolve(); await vi.advanceTimersByTimeAsync(MARKET_CURRENT_POLL_INTERVAL_MS * 2); });
    expect(refresh).toHaveBeenCalledTimes(1);
    view.unmount();
    vi.useRealTimers();
  });
});
