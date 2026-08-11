import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "../routes/router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../features/auth/AuthContext";
import type { EnhancedReport, Interpretation, PathMatrix, Principal, Report, Sector, SectorResearch } from "../types";

const report: Report = {
  id: "report-1", title: "虚构岛屿研究周报", report_date: "2026-07-19", candidate_report_date: "2026-07-19", report_date_confirmed: true,
  detected_report_date: "2026-07-19", report_date_source: "pdf_title", report_date_confidence: "high", report_date_confirmed_by_user: false,
  market_as_of_date: "2026-07-17", candidate_market_as_of_date: "2026-07-17", market_as_of_date_confirmed: true, enhanced_status: "ready", enhanced_revision_number: 1,
  interpretation_status: "ready",
  status: "published", core_view: "保持耐心，观察结构性机会。", market_path: "3844点以下继续防守；即使站上，也必须通过时间、市场宽度和量能验证。", risk_warning: "仅为测试。", focus_sectors: ["半导体", "恒生科技"],
  created_at: "2026-07-19T20:00:00Z", published_at: "2026-07-19T21:00:00Z", pdf_url: "/api/v1/reports/report-1/pdf", pdf_download_url: "/api/v1/reports/report-1/pdf/download", data_notice: "研究辅助数据，非生产级行情服务。",
  mentions: [{ sector_key: "semiconductor", sector_name: "半导体", summary: "关注需求验证。", extraction_status: "explicit" }], raw_text: "fixture", original_filename: "fixture.pdf", unmapped_terms: [],
};

const sectors: Sector[] = Array.from({ length: 67 }, (_, index) => ({
  sector_key: index === 64 ? "hotel" : index === 65 ? "catering" : index === 66 ? "hang_seng_tech" : `sector-${index + 1}`,
  sector_name: index === 64 ? "酒店" : index === 65 ? "餐饮" : index === 66 ? "恒生科技" : `板块${index + 1}`,
  parent_report_topic: index === 64 || index === 65 ? "hotel_catering" : index === 66 ? "hang_seng_tech" : `sector-${index + 1}`,
  report_topic_name: index === 64 || index === 65 ? "酒店餐饮" : index === 66 ? "恒生科技" : `板块${index + 1}`,
  group_name: `分组${Math.floor(index / 9) + 1}`,
  group_order: Math.floor(index / 9) + 1,
  overall_order: index + 1,
  latest_view: index === 66 ? "直播观点正常展示" : null,
  mentioned_in_latest_published: index === 66,
  market_support_status: index === 66 ? "unsupported" : "supported",
  data_status: index === 64 ? "proxy" : index === 65 ? "unverified" : index === 66 ? "unsupported" : "supported",
  market_status_detail: index === 64 ? "酒店（旅游及酒店代理口径）" : index === 65 ? "餐饮行情源待验证" : index === 66 ? "港股跨市场行情暂未接入" : "研究辅助数据",
  current_path_status: index === 66 ? "watch" : "not_mentioned",
  current_path_status_label: index === 66 ? "观察" : "未提",
  effective_status: index === 0 ? "hold" : index === 66 ? "watch" : "not_mentioned",
  effective_status_label: index === 0 ? "持有" : index === 66 ? "观察" : "未提",
  strict_holding_interval: index === 0 ? { status: "active", start_report_date: "2026-07-15", start_market_as_of_date: "2026-07-15", eod_return: 1.25, calculation_status: "complete_eod" } : null,
  broad_holding_interval: index === 0 ? { status: "active", start_report_date: "2026-07-15", start_market_as_of_date: "2026-07-15", eod_return: 2.5, calculation_status: "complete_eod" } : null,
  is_low_attention: false,
  is_pinned_for_research: false,
  recent_mention_count: index === 0 ? 3 : 0,
  attention_level: index === 0 ? "high" : "normal",
  intraday_status: index === 0 ? "intraday_fresh" : index === 66 ? "unsupported" : "provider_failed",
  intraday_snapshot: index === 0 ? { sector_key: "sector-1", trade_date: "2026-07-28", observed_at: "07/28 14:20", index_value: 101, pre_close: 100, pct_change: 1.26, volume: null, amount: null, provider: "eastmoney_board_spot", provider_role: "research_provider", data_status: "intraday_fresh", fetched_at: "2026-07-28T06:20:00Z", intraday_ma5: 99.2, intraday_vs_ma5: 1.81 } : null,
  intraday_last_attempt_at: "07/28 14:20",
  latest_market: index === 0 ? { trade_date: "2026-07-27", close: 101, pre_close: 100, daily_pct_change: 1, return_5d: 1.86, return_10d: 2, return_20d: 3, ma5: 100, ma10: 99, ma20: 98, close_vs_ma5_pct: 1.97, close_vs_ma10_pct: 2, close_vs_ma20_pct: .61, volume: 100, volume_average_5d: 90, volume_average_20d: 80, volume_ratio_5d: 1.1, volume_ratio_20d: 1.25, amount: null, history_status: "complete", eod_status: "complete_eod", data_source: "fixture", provider_role: "research_provider", fetched_at: "2026-07-27T08:00:00Z", source_response_hash: "a".repeat(64) } : null,
  timeline: index === 1 ? [{ report_id: "report-1", report_date: "2026-07-19", report_title: report.title, summary: "关注需求验证。" }] : [],
}));

const pathEntry = { id: "path-1", sector_key: "semiconductor", sector_name: "半导体", path_status: "hold" as const, path_status_label: "持有", path_status_color: "#15803d", explicitly_mentioned: true, judgement_summary: "关注需求验证。", source_text_reference: "fixture", review_status: "confirmed", manually_modified: false, revision_id: "initial" };
const assessment = { id: "assessment-1", sector_key: "semiconductor", sector_name: "半导体", current_path_status: "hold" as const, path_status_label: "持有", explicitly_mentioned: true, recent_path_summary: "观察转持有", current_judgement: "关注需求验证。", main_basis: "量价结构", observation_condition: "需求确认", source_section: "板块详细汇总", source_text_reference: "fixture", review_status: "confirmed", manually_modified: false, revision_id: "initial", market: null };
const enhanced: EnhancedReport = { report, path_entries: [pathEntry], sector_assessments: [assessment], status_groups: [{ status: "hold", count: 1, items: [assessment] }], market_snapshots: [], comparison: { previous_report_id: null, status_changes: [], counts: {} }, market_data_attached: false, data_notice: report.data_notice };
const enhancedWithShanghaiAnchor: EnhancedReport = {
  ...enhanced,
  market_snapshots: [{
    ...sectors[0].latest_market!,
    sector_key: "shanghai_composite",
    close: 3502.1,
    daily_pct_change: 1.2,
    ma5: 3488.6,
    ma20: 3420.2,
  }],
  market_data_attached: true,
};
const interpretation: Interpretation = {
  report_id: report.id, status: "ready", report_date: report.report_date, detected_report_date: report.detected_report_date,
  report_date_source: "pdf_title", report_date_confidence: "high", report_date_confirmed_by_user: false,
  candidate_market_as_of_date: report.candidate_market_as_of_date, market_as_of_date: null, market_data_status: "not_bound",
  field_provenance: {}, attention_items: [], mapping_summary: { confirmed: 1, probable: 0, unmapped: 0, conflict: 0 },
  status_counts: { avoid: 0, strong_watch: 0, watch: 0, weak_watch: 0, turn_hold: 0, hold: 1, turn_weak: 0, exit: 0, not_mentioned: 65 },
  mentioned_assessments: [assessment], relevant_path_entries: [pathEntry], all_path_entries: [{ ...pathEntry, group_name: "科技硬件与通信" }],
  path_entry_count: 66, external_llm_calls: 0, ocr_used: false,
  quality_status: "verified_structure", quality_summary: { report_structure: "verified_structure", history_matrix: "verified_structure", history_rows: 66, assessment_rows: 1, assessment_verified: 1, assessment_blocking: 0 }, pdf_history_matrix: { dates: [], rows: [] },
  review_workflow: { workflow_status: "ready_to_publish", summary: { auto_confirmed: 66, suggested_review: 0, must_handle: 0, handled: 0 }, steps: [{ key: "upload", label: "上传报告", state: "complete" }, { key: "review", label: "检查疑问", state: "complete" }, { key: "publish", label: "发布报告", state: "current" }], issues: [] },
};
const matrix: PathMatrix = { caption: "板块历史路径矩阵", dates: [{ report_id: report.id, detail_report_id: report.id, has_detailed_report: true, report_date: report.report_date!, market_as_of_date: report.market_as_of_date, market_weekday: "周五", weekday: "周日", is_weekend_report: true }], groups: [{ group_order: 1, group_name: "科技硬件与通信", sector_count: 1 }], rows: [{ sector_key: "semiconductor", sector_name: "半导体", group_name: "科技硬件与通信", group_order: 1, overall_order: 1, cells: [{ ...pathEntry, report_id: report.id, detail_report_id: report.id, has_detailed_report: true, report_date: report.report_date! }] }], status_contract: { statuses: [{ code: "hold", label: "持有", color: "#15803d", order: 1 }] } };
const research: SectorResearch = { sector_key: "sector-2", sector_name: "板块2", group_name: "分组1", latest_explicit_view: { report_id: report.id, report_date: report.report_date!, path: pathEntry, assessment, report_snapshot: null }, current_latest_market: null, market_support_status: "supported", data_status: "supported", market_status_detail: "研究辅助数据", history: [{ report_id: report.id, report_date: report.report_date!, path: pathEntry, assessment, report_snapshot: null }] };

function response(payload: unknown, status = 200) { return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } })); }
function mockApi(options: { empty?: boolean; duplicate?: boolean; enhancedReport?: EnhancedReport } = {}) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/reports/latest")) return options.empty ? response({ error: { code: "no_published_report", message: "none" } }, 404) : response(report);
    if (url.endsWith("/reports/report-1/enhanced")) return response(options.enhancedReport ?? enhanced);
    if (url.endsWith("/reports/report-1/pdf/preview")) return response({ page_count: 2, page_urls: ["/preview/1", "/preview/2"], render_mode: "server_memory_png" });
    if (url.includes("/reports/report-1/path-matrix")) return response(matrix);
    if (url.endsWith("/reports") && !url.includes("admin")) return response(options.empty ? [] : [report]);
    if (url.includes("/reports/report-1") && !url.includes("admin")) return response(report);
    if (url.includes("/sectors?")) return response(sectors);
    if (url.endsWith("/auth/me")) return response({ username: "viewer", role: "viewer" });
    if (url.endsWith("/market/intraday/status")) return response({ session_status: "running", market_phase: "intraday_open", market_phase_detail: "intraday_open", intraday_trade_date: "2026-07-28", refresh_interval_minutes: 5, provider: "eastmoney_board_spot", provider_role: "research_provider", production_primary: null, production_primary_approved: false, research_notice: "研究辅助数据", last_refresh_at: "07/28 14:20", last_attempt_at: "07/28 14:20", next_refresh_at: "07/28 14:25", latest_snapshot_at: "07/28 14:20", success_count: 8, failure_count: 58, stale_count: 0, supported_market_path_count: 66, unsupported_count: 1, viewer_provider_access: false, auto_start: true });
    if (url.includes("/sectors/sector-2/research")) return response(research);
    if (url.includes("/sectors/semiconductor/research")) return response({ ...research, sector_key: "semiconductor", sector_name: "半导体" });
    if (url.includes("/sectors/sector-2")) return response(sectors[1]);
    if (url.endsWith("/admin/summary")) return response({ drafts: 1, needs_review: 1, published: 1, parse_failed: 0, unmapped_terms: 0 });
    if (url.includes("/admin/report-days?")) return response([]);
    if (url.endsWith("/admin/reports/interpret")) return response({ report, interpretation, duplicate: options.duplicate ?? false, interpretation_error: null, processing_steps: [] }, 201);
    if (url.endsWith("/admin/reports/report-1/interpretation")) return response({ report, interpretation });
    if (url.endsWith("/admin/reports") && !url.includes("report-1")) return response({ report: report, interpretation, duplicate: options.duplicate ?? false }, 201);
    if (url.includes("/admin/reports/report-1")) return response({ ...report, status: "needs_review" });
    return response({ error: { code: "not_found", message: "not found" } }, 404);
  }));
}
function renderAt(path: string, principal: Principal | null = { username: "viewer", role: "viewer" }) { return render(<MemoryRouter initialEntries={[path]}><AuthProvider initialPrincipal={principal}><App /></AuthProvider></MemoryRouter>); }

describe("Viewer research pages", () => {
  beforeEach(() => mockApi());
  it("shows a friendly empty home state", async () => { mockApi({ empty: true }); renderAt("/"); expect(await screen.findByText("暂无已发布报告。")).toBeInTheDocument(); });
  it("shows the latest published report with a factual market anchor and structured defense line", async () => { renderAt("/"); expect(await screen.findByRole("heading", { name: report.title })).toBeInTheDocument(); expect(screen.getByText(report.core_view)).toBeInTheDocument(); expect(screen.getByText("猎豹核心判断")).toBeInTheDocument(); expect(screen.getByText("当天大A行情锚点")).toBeInTheDocument(); expect(screen.getByText("上证指数")).toBeInTheDocument(); expect(screen.getByText("行情未附加")).toBeInTheDocument(); expect(screen.getByText("3844 点")).toBeInTheDocument(); expect(screen.getByText("次日需要关注的攻防线")).toBeInTheDocument(); });
  it("uses an existing Shanghai snapshot without requesting a new market source", async () => { mockApi({ enhancedReport: enhancedWithShanghaiAnchor }); renderAt("/"); expect(await screen.findByText("3502.1")).toBeInTheDocument(); expect(screen.getByText("+1.20%")).toBeInTheDocument(); expect(screen.getByText("3488.6")).toBeInTheDocument(); expect(screen.getByText("3420.2")).toBeInTheDocument(); expect(screen.queryByText("行情未附加")).not.toBeInTheDocument(); });
  it("shows the report list without weekend missing warnings", async () => { renderAt("/reports"); expect(await screen.findByRole("table", { name: "已发布报告" })).toBeInTheDocument(); expect(screen.getByText(/周五、周六无报告属于正常节奏/)).toBeInTheDocument(); });
  it("shows report details without requesting PDF or preview pages until requested", async () => { const user = userEvent.setup(); renderAt("/reports/report-1"); expect(await screen.findByRole("heading", { level: 1, name: report.title })).toBeInTheDocument(); expect(screen.getByRole("table", { name: /板块历史路径矩阵/ })).toBeInTheDocument(); expect(screen.getByRole("button", { name: "最近20期" })).toHaveClass("active"); expect(screen.queryByLabelText("原始PDF逐页预览")).not.toBeInTheDocument(); expect(screen.getByRole("link", { name: "下载原始PDF" })).toHaveAttribute("href", report.pdf_download_url); expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/pdf/preview"), expect.anything()); await user.click(screen.getByRole("button", { name: "加载逐页预览" })); expect(await screen.findByLabelText("原始PDF逐页预览")).toBeInTheDocument(); expect(screen.getByAltText("原始PDF第1页")).toHaveAttribute("src", "/preview/1"); });
  it("renders 67 market paths from 66 report topics in eight fixed groups", async () => { renderAt("/sectors"); const table = await screen.findByRole("table", { name: /板块研究档案/ }); expect(within(table).getAllByRole("row")).toHaveLength(76); expect(screen.getByRole("navigation", { name: "板块研究一级分组快捷导航" }).querySelectorAll("button")).toHaveLength(8); });
  it("keeps one realtime column and reports partial live coverage honestly", async () => { renderAt("/sectors"); const table = await screen.findByRole("table", { name: /板块研究档案/ }); expect(screen.getByText("实时行情 8/66")).toBeInTheDocument(); expect(screen.getByText("暂无数据58项")).toBeInTheDocument(); expect(screen.getByText("更新14:20")).toBeInTheDocument(); expect(within(table).getByRole("columnheader", { name: "实时行情" })).toBeInTheDocument(); expect(within(table).queryByRole("columnheader", { name: "完整行情" })).not.toBeInTheDocument(); expect(within(table).getByText("+1.26%")).toBeInTheDocument(); expect(within(table).getAllByText("暂无实时").length).toBeGreaterThan(0); expect(table).not.toHaveTextContent("2026-07-28T"); });
  it("shows hotel and catering as independent market paths under one report topic", async () => { renderAt("/sectors"); expect(await screen.findByRole("link", { name: "酒店" })).toHaveAttribute("href", "/sectors/hotel"); expect(screen.getByRole("link", { name: "餐饮" })).toHaveAttribute("href", "/sectors/catering"); expect(screen.getAllByText("报告主题：酒店餐饮")).toHaveLength(2); expect(screen.getByText("代理口径")).toBeInTheDocument(); expect(screen.getByText("行情待验证")).toBeInTheDocument(); });
  it("separates HSTECH opinion and unsupported market status", async () => { renderAt("/sectors"); expect(await screen.findByTitle("直播观点正常展示")).toBeInTheDocument(); expect(screen.getByText("暂不支持")).toBeInTheDocument(); });
  it("shows compact strict and broad holding results", async () => { renderAt("/sectors"); expect(await screen.findByText("绝对 +1.25%")).toBeInTheDocument(); expect(screen.getByText("广义 +2.50%")).toBeInTheDocument(); });
  it("shows realtime MA5 and an accessible holding explanation", async () => { const user = userEvent.setup(); renderAt("/sectors"); expect(await screen.findByText("实时MA5 ↑1.81%")).toBeInTheDocument(); expect(screen.getByText("正式MA20 ↑0.61%")).toBeInTheDocument(); expect(screen.getByText(/只连续计算“转持、持有”/)).toBeVisible(); const summary = screen.getByText("查看详细定义"); expect(summary.parentElement).not.toHaveAttribute("open"); await user.click(summary); expect(summary.parentElement).toHaveAttribute("open"); expect(screen.getByText(/“未提”沿用上一期有效状态/)).toBeVisible(); });
  it("uses compact matrix headers, sticky group label and catalog navigation", async () => { renderAt("/reports/report-1"); const table = await screen.findByRole("table", { name: /板块历史路径矩阵/ }); const headers = Array.from(table.querySelectorAll("thead th")).map(item => item.textContent ?? ""); expect(headers.some(item => item.includes("报告"))).toBe(false); expect(headers.some(item => item.includes("7/19") && item.includes("日") && item.includes("行7/17") && item.includes("五"))).toBe(true); expect(screen.getByRole("navigation", { name: "一级分组快捷导航" })).toBeInTheDocument(); expect(table.querySelector(".matrix-group-label.sticky-sector")).toHaveTextContent("科技硬件与通信"); const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toMatch(/\.path-matrix thead th[^}]*width:\s*80px/); });
  it("shows a sector opinion timeline", async () => { renderAt("/sectors/sector-2"); expect(await screen.findAllByText("关注需求验证。")).not.toHaveLength(0); });
  it("exposes readable attribution and license links", () => { renderAt("/about", null); expect(screen.getByRole("heading", { name: "项目与第三方组件说明" })).toBeVisible(); expect(screen.getByRole("link", { name: "查看原项目" })).toHaveAttribute("href", "https://github.com/guokaigdg/animal-island-ui"); expect(screen.getByRole("link", { name: /CC BY-NC 4.0/ })).toHaveAttribute("href", "https://creativecommons.org/licenses/by-nc/4.0/"); });
});

describe("Admin workflow and permissions", () => {
  beforeEach(() => mockApi());
  it("redirects a viewer away from admin routes", async () => { renderAt("/admin", { username: "viewer", role: "viewer" }); expect(await screen.findByRole("heading", { name: "登录研究手册" })).toBeInTheDocument(); });
  it("redirects an unauthenticated visitor to login", async () => { renderAt("/reports", null); expect(await screen.findByRole("heading", { name: "登录研究手册" })).toBeInTheDocument(); });
  it("allows an admin to see the dashboard", async () => { renderAt("/admin", { username: "admin", role: "admin" }); expect(await screen.findByRole("heading", { name: "最近两周直播日程" })).toBeInTheDocument(); });
  it("shows one upload-and-interpret action without technical parse buttons", () => { renderAt("/admin/reports/new", { username: "admin", role: "admin" }); expect(screen.getByRole("button", { name: "上传并解读" })).toBeInTheDocument(); expect(screen.queryByRole("button", { name: "本地解析" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "增强解析" })).not.toBeInTheDocument(); });
  it("rejects an invalid PDF in the browser", () => { renderAt("/admin/reports/new", { username: "admin", role: "admin" }); const input = document.querySelector('input[type="file"]') as HTMLInputElement; fireEvent.change(input, { target: { files: [new File(["bad"], "bad.txt", { type: "text/plain" })] } }); expect(screen.getByRole("alert")).toHaveTextContent("请选择有效 PDF 文件"); });
  it("shows progress and automatically opens the interpretation result", async () => { mockApi({ duplicate: true }); const user = userEvent.setup(); renderAt("/admin/reports/new", { username: "admin", role: "admin" }); const input = document.querySelector('input[type="file"]') as HTMLInputElement; await user.upload(input, new File(["%PDF-fixture"], "fixture.pdf", { type: "application/pdf" })); expect(await screen.findByText("解读完成")).toBeInTheDocument(); expect(await screen.findByRole("heading", { name: report.title })).toBeInTheDocument(); });
  it("renders the three-step review summary and only one primary publish action", async () => { renderAt("/admin/reports/report-1/interpretation", { username: "admin", role: "admin" }); expect(await screen.findByText(report.core_view)).toBeInTheDocument(); expect(screen.getByText(report.market_path)).toBeInTheDocument(); expect(screen.getAllByText("上传报告").length).toBeGreaterThan(0); expect(screen.getByText("自动确认")).toBeInTheDocument(); expect(screen.getByText("建议检查")).toBeInTheDocument(); expect(screen.getByText("必须处理")).toBeInTheDocument(); expect(screen.getAllByRole("button", { name: "确认并发布" })).toHaveLength(1); expect(screen.queryByRole("button", { name: "本地解析" })).not.toBeInTheDocument(); });
  it("keeps raw text, all 66 paths and technical controls collapsed", async () => { renderAt("/admin/reports/report-1/interpretation", { username: "admin", role: "admin" }); expect(await screen.findByText("查看全部66个板块路径")).toBeInTheDocument(); expect(screen.getByText("高级技术信息")).toBeInTheDocument(); expect(screen.queryByText("fixture")).not.toBeVisible(); });
});

describe("Accessibility foundations", () => {
  beforeEach(() => mockApi());
  it("supports keyboard focus on primary navigation", async () => { const user = userEvent.setup(); renderAt("/"); await user.tab(); expect(document.activeElement).toHaveAttribute("href", "/"); });
  it("uses text and symbols for status, not color alone", async () => { renderAt("/sectors"); expect(await screen.findByText("暂不支持")).toHaveTextContent("暂不支持"); });
  it("declares reduced-motion behavior", () => { const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toContain("prefers-reduced-motion"); });
  it("keeps narrative copy at normal weight", () => { const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toMatch(/body\s*\{[^}]*font-weight:\s*400/); expect(css).toMatch(/pdf-assessment-table td:nth-child\(4\)[^}]*font-weight:\s*400/); expect(css).toMatch(/pdf-assessment-table td:nth-child\(5\)[^}]*font-weight:\s*400/); expect(css).toMatch(/\.sector-table\s*\{[^}]*PingFang SC[^}]*font-size:\s*13px/); expect(css).toMatch(/\.sector-table thead th[^}]*font-weight:\s*600[^}]*white-space:\s*nowrap/); expect(css).toMatch(/\.sector-table td[^}]*font-weight:\s*400/); expect(css).toMatch(/\.realtime-cell b[^}]*font-size:\s*14px[^}]*font-weight:\s*600/); });
  it("includes responsive layout rules", () => { const css = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8"); expect(css).toContain("@media (max-width: 760px)"); });
});
