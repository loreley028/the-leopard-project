import { expect, test } from "vitest";
import { apiPath, appPath, appRoute } from "../config/appBasePath";
import { publicResourcePath } from "../api/client";

test("base-path helpers preserve origin-root development defaults", () => {
  expect(appPath("/reports")).toBe("/reports");
  expect(apiPath("/reports")).toBe("/api/v1/reports");
  expect(publicResourcePath("/api/v1/reports/r-1/pdf/download")).toBe("/api/v1/reports/r-1/pdf/download");
});

test("base-path helpers namespace routes, APIs and PDF resources under leopard", () => {
  expect(appPath("/sectors/cpo", "/leopard/")).toBe("/leopard/sectors/cpo");
  expect(appPath("/api/v1/reports/r-1/pdf/download", "/leopard")).toBe("/leopard/api/v1/reports/r-1/pdf/download");
  expect(appRoute("/leopard/sectors/cpo", "/leopard/")).toBe("/sectors/cpo");
  expect(appRoute("/leopard", "/leopard/")).toBe("/");
});
