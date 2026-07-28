import { describe, expect, it } from "vitest";
import { judgementDetail, pdfGroup } from "../utils/judgement";

describe("judgement presentation policy", () => {
  it("does not repeat a bare path status", () => {
    expect(judgementDetail("hold", "继续持有。 ")).toBe("");
    expect(judgementDetail("watch", "观察；")).toBe("");
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
