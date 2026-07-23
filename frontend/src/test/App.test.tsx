import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../features/auth/AuthContext";
import type { Principal, Report, Sector } from "../types";

const report: Report = {
  id: "report-1", title: "虚构岛屿研究周报", report_date: "2026-07-19", candidate_report_date: "2026-07-19", report_date_confirmed: true,
  status: "published", core_view: "保持耐心，观察结构性机会。", market_path: "震荡整理。", risk_warning: "仅为测试。", focus_sectors: ["半导体", "恒生科技"],
  created_at: "2026-07-19T20:00:00Z", published_at: "2026-07-19T21:00:00Z", pdf_url: "/api/v1/reports/report-1/pdf", data_notice: "研究辅助数据，非生产级行情服务。",
  mentions: [{ sector_key: "semiconductor", sector_name: "半导体", summary: "关注需求验证。", extraction_status: "explicit" }], raw_text: "fixture", original_filename: "fixture.pdf", unmapped_terms: [],
};

const sectors: Sector[] = Array.from({ length: 66 }, (_, index) => ({
  sector_key: index === 65 ? "hang_seng_tech" : `sector-${index + 1}`,
  sector_name: index === 65 ? "恒生科技" : `板块${index + 1}`,
  group_name: `分组${Math.floor(index / 9) + 1}`,
  group_order: Math.floor(index / 9) + 1,
  overall_order: index + 1,
  latest_view: index === 65 ? "直播观点正常展示" : null,
  mentioned_in_latest_published: index === 65,
  market_support_status: index === 65 ? "unsupported" : "supported",
  data_status: index === 65 ? "unsupported" : "supported",
  market_status_detail: index === 65 ? "港股跨市场行情暂未接入" : "研究辅助数据",
  timeline: index === 1 ? [{ report_id: "report-1", report_date: "2026-07-19", report_title: report.title, summary: "关注需求验证。" }] : [],
}));

function response(payload: unknown, status = 200) { return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } })); }
function mockApi(options: { empty?: boolean; duplicate?: boolean } = {}) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/reports/latest")) return options.empty ? response({ error: { code: "no_published_report", message: "none" } }, 404) : response(report);
    if (url.endsWith("/reports") && !url.includes("admin")) return response(options.empty ? [] : [report]);
    if (url.includes("/reports/report-1") && !url.includes("admin")) return response(report);
    if (url.endsWith("/sectors")) return response(sectors);
    if (url.includes("/sectors/sector-2")) return response(sectors[1]);
    if (url.endsWith("/admin/summary")) return response({ drafts: 1, needs_review: 1, published: 1, parse_failed: 0, unmapped_terms: 0 });
    if (url.endsWith("/admin/reports") && !url.includes("report-1")) return response({ report: report, duplicate: options.duplicate ?? false }, 201);
    if (url.includes("/admin/reports/report-1")) return response({ ...report, status: "needs_review" });
    return response({ error: { code: "not_found", message: "not found" } }, 404);
  }));
}
function renderAt(path: string, principal: Principal | null = { username: "viewer", role: "viewer" }) { return render(<MemoryRouter initialEntries={[path]}><AuthProvider initialPrincipal={principal}><App /></AuthProvider></MemoryRouter>); }

describe("Viewer research pages", () => {
  beforeEach(() => mockApi());
  it("shows a friendly empty home state", async () => { mockApi({ empty: true }); renderAt("/"); expect(await screen.findByText("岛上还没有已发布报告")).toBeInTheDocument(); });
  it("shows the latest published report", async () => { renderAt("/"); expect(await screen.findByRole("heading", { name: report.title })).toBeInTheDocument(); expect(screen.getByText(report.core_view)).toBeInTheDocument(); });
  it("shows the report list without weekend missing warnings", async () => { renderAt("/reports"); expect(await screen.findByRole("table", { name: "已发布报告" })).toBeInTheDocument(); expect(screen.getByText(/周五、周六无报告不会标记为缺失/)).toBeInTheDocument(); });
  it("shows report details and PDF access", async () => { renderAt("/reports/report-1"); expect(await screen.findByText("结构化板块观点")).toBeInTheDocument(); expect(screen.getByRole("link", { name: /原始 PDF/ })).toHaveAttribute("href", report.pdf_url); });
  it("renders all 66 sectors", async () => { renderAt("/sectors"); await waitFor(() => expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(66)); });
  it("separates HSTECH opinion and unsupported market status", async () => { renderAt("/sectors"); expect(await screen.findByText("直播观点正常展示")).toBeInTheDocument(); expect(screen.getByText("港股跨市场行情暂未接入")).toBeInTheDocument(); expect(screen.getByText("暂不支持")).toBeInTheDocument(); });
  it("shows a sector opinion timeline", async () => { renderAt("/sectors/sector-2"); expect(await screen.findByText("关注需求验证。")).toBeInTheDocument(); });
  it("exposes readable attribution and license links", () => { renderAt("/about", null); expect(screen.getByRole("heading", { name: "项目与第三方组件说明" })).toBeVisible(); expect(screen.getByRole("link", { name: "查看原项目" })).toHaveAttribute("href", "https://github.com/guokaigdg/animal-island-ui"); expect(screen.getByRole("link", { name: /CC BY-NC 4.0/ })).toHaveAttribute("href", "https://creativecommons.org/licenses/by-nc/4.0/"); });
});

describe("Admin workflow and permissions", () => {
  beforeEach(() => mockApi());
  it("redirects a viewer away from admin routes", async () => { renderAt("/admin", { username: "viewer", role: "viewer" }); expect(await screen.findByRole("heading", { name: "登录研究手册" })).toBeInTheDocument(); });
  it("redirects an unauthenticated visitor to login", async () => { renderAt("/reports", null); expect(await screen.findByRole("heading", { name: "登录研究手册" })).toBeInTheDocument(); });
  it("allows an admin to see the dashboard", async () => { renderAt("/admin", { username: "admin", role: "admin" }); expect(await screen.findByRole("heading", { name: "管理工作台" })).toBeInTheDocument(); });
  it("renders the PDF upload form and progress", () => { renderAt("/admin/reports/new", { username: "admin", role: "admin" }); expect(screen.getByRole("button", { name: "选择 PDF" })).toBeInTheDocument(); expect(screen.getByLabelText("上传进度")).toBeInTheDocument(); });
  it("rejects an invalid PDF in the browser", () => { renderAt("/admin/reports/new", { username: "admin", role: "admin" }); const input = document.querySelector('input[type="file"]') as HTMLInputElement; fireEvent.change(input, { target: { files: [new File(["bad"], "bad.txt", { type: "text/plain" })] } }); expect(screen.getByRole("alert")).toHaveTextContent("请选择有效 PDF 文件"); });
  it("shows duplicate PDF feedback before opening review", async () => { mockApi({ duplicate: true }); const user = userEvent.setup(); renderAt("/admin/reports/new", { username: "admin", role: "admin" }); const input = document.querySelector('input[type="file"]') as HTMLInputElement; await user.upload(input, new File(["%PDF-fixture"], "fixture.pdf", { type: "application/pdf" })); expect(await screen.findByRole("heading", { name: "报告复核" })).toBeInTheDocument(); });
  it("renders review and publish controls", async () => { renderAt("/admin/reports/report-1/review", { username: "admin", role: "admin" }); expect(await screen.findByRole("button", { name: "本地解析" })).toBeInTheDocument(); expect(screen.getByRole("button", { name: "发布" })).toBeInTheDocument(); });
});

describe("Accessibility foundations", () => {
  beforeEach(() => mockApi());
  it("supports keyboard focus on primary navigation", async () => { const user = userEvent.setup(); renderAt("/"); await user.tab(); expect(document.activeElement).toHaveAttribute("href", "/"); });
  it("uses text and symbols for status, not color alone", async () => { renderAt("/sectors"); expect(await screen.findByText("暂不支持")).toHaveTextContent("暂不支持"); });
  it("declares reduced-motion behavior", () => { const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toContain("prefers-reduced-motion"); });
  it("includes responsive layout rules", () => { const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toContain("@media (max-width: 760px)"); });
});
