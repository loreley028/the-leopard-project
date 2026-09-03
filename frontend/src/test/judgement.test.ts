import { describe, expect, it } from "vitest";
import { judgementDetail, pdfGroup } from "../utils/judgement";

describe("judgement presentation policy", () => {
  it("does not repeat a bare path status", () => {
    expect(judgementDetail("hold", "继续持有。 ")).toBe("");
    expect(judgementDetail("watch", "观察；")).toBe("");
  });

  it("does not expose internal qualification combined with the status", () => {
    expect(judgementDetail("turn_hold", "持有区 · 转持")).toBe("");
    expect(judgementDetail("strong_watch", "观察区 · **强观**")).toBe("");
    expect(judgementDetail("turn_weak", "风险转折 · 转弱")).toBe("");
    expect(judgementDetail("avoid", "回避区 · 不碰")).toBe("");
  });

  it("retains substantive judgement text", () => {
    expect(judgementDetail("watch", "观察需求验证和量价结构。"))
      .toBe("观察需求验证和量价结构。");
  });

  it("maps every status into one PDF-level group", () => {
    expect(pdfGroup("hold")).toBe("B1 继续持有");
    expect(pdfGroup("turn_weak")).toBe("B2 重点观察区");
    expect(pdfGroup("avoid")).toBe("B3 当前不碰");
  });
});
