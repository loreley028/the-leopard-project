import { describe, expect, it } from "vitest";
import { marketSnapshotDisplayState } from "../utils/marketSnapshotDisplay";

describe("market snapshot display state", () => {
  it("uses only the upstream quote timestamp during continuous trading and lunch", () => {
    expect(marketSnapshotDisplayState("morning_trading", "2026-08-20T09:31:12+08:00")).toBe("盘中 09:31");
    expect(marketSnapshotDisplayState("afternoon_trading", "2026-08-20T14:26:34+08:00")).toBe("盘中 14:26");
    expect(marketSnapshotDisplayState("lunch_break", "2026-08-20T11:30:00+08:00")).toBe("午间 11:30");
  });

  it("never calls a pre-open or non-trading snapshot today's close", () => {
    expect(marketSnapshotDisplayState("pre_open", "2026-08-20T15:00:00+08:00")).toBe("最近收盘 · 08-20");
    expect(marketSnapshotDisplayState("non_trading_day", null)).toBe("最近收盘");
  });

  it("labels same-day close separately after 15:00", () => {
    expect(marketSnapshotDisplayState("after_close", "2026-08-20T15:00:00+08:00")).toBe("今日收盘 · 15:00");
  });
});
