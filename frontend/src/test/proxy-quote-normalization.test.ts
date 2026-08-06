import { describe, expect, it } from "vitest";
import { parseFiniteNumber } from "../api/client";

describe("parseFiniteNumber", () => {
  it("preserves finite numbers and converts numeric strings", () => {
    expect(parseFiniteNumber(12.5)).toBe(12.5);
    expect(parseFiniteNumber(" -1.56 ")).toBe(-1.56);
  });

  it("fails closed for missing, empty, non-finite, and malformed values", () => {
    for (const value of [null, undefined, "", "  ", "not-a-number", NaN, Infinity, -Infinity, {}, []]) {
      expect(parseFiniteNumber(value)).toBeNull();
    }
  });
});
