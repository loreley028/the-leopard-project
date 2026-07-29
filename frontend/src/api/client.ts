import type { EnhancedReport, Interpretation, IntradayStatus, PathMatrix, Principal, Report, Sector, SectorAssessment, SectorResearch } from "../types";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include", ...init });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: { code: "request_failed", message: "请求失败" } }));
    throw new ApiError(payload.error?.code ?? "request_failed", payload.error?.message ?? "请求失败", response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) => request<Principal>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<Principal>("/auth/me"),
  reports: () => request<Report[]>("/reports"),
  latestReport: () => request<Report>("/reports/latest"),
  report: (id: string) => request<Report>(`/reports/${id}`),
  enhancedReport: (id: string) => request<EnhancedReport>(`/reports/${id}/enhanced`),
  pathMatrix: (id: string, period = "20") => request<PathMatrix>(`/reports/${id}/path-matrix?periods=${encodeURIComponent(period)}`),
  reportAssessments: (id: string) => request<SectorAssessment[]>(`/reports/${id}/sector-assessments`),
  sectors: (includeLowAttention = false, lowAttentionOnly = false) => request<Sector[]>(`/sectors?include_low_attention=${includeLowAttention}&low_attention_only=${lowAttentionOnly}`),
  sector: (key: string) => request<Sector>(`/sectors/${key}`),
  sectorResearch: (key: string, pathPeriods = 20, marketDays = 20) => request<SectorResearch>(`/sectors/${key}/research?path_periods=${pathPeriods}&market_days=${marketDays}`),
  adminSummary: () => request<Record<string, number>>("/admin/summary"),
  reportDays: (start: string, end: string) => request<Array<{ report_date: string; weekday: string; expected_status: string; state: string; skip_reason: string; reports: Report[] }>>(`/admin/report-days?start=${start}&end=${end}`),
  skipReportDay: (day: string, reason = "") => request(`/admin/report-days/${day}/skip`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }),
  cancelReportDaySkip: (day: string) => request<void>(`/admin/report-days/${day}/skip`, { method: "DELETE" }),
  adminReports: () => request<Report[]>("/admin/reports"),
  adminReport: (id: string) => request<Report>(`/admin/reports/${id}`),
  interpret: (file: File, reportDate?: string) => { const body = new FormData(); body.append("file", file); if (reportDate) body.append("report_date_hint", reportDate); return request<{ report: Report; interpretation: Interpretation; duplicate: boolean; interpretation_error: { code: string; message: string } | null; processing_steps: string[] }>("/admin/reports/interpret", { method: "POST", body }); },
  upload: (file: File) => { const body = new FormData(); body.append("file", file); return request<{ report: Report; interpretation: Interpretation; duplicate: boolean }>("/admin/reports", { method: "POST", body }); },
  interpretation: (id: string) => request<{ report: Report; interpretation: Interpretation }>(`/admin/reports/${id}/interpretation`),
  interpretationStatus: (id: string) => request<{ report_id: string; status: string; attention_count: number; recoverable: boolean }>(`/admin/reports/${id}/interpretation-status`),
  patchInterpretation: (id: string, changes: object) => request<{ report: Report; interpretation: Interpretation }>(`/admin/reports/${id}/interpretation`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }),
  resolveReviewIssue: (id: string, issueKey: string, finalValue: unknown, resolutionSource: "accepted_suggestion" | "manual_override", optionalNote = "") => request<{ report: Report; interpretation: Interpretation }>(`/admin/reports/${id}/review-issues/${encodeURIComponent(issueKey)}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ final_value: finalValue, resolution_source: resolutionSource, optional_note: optionalNote }) }),
  bulkAcceptReviewIssues: (id: string) => request<{ report: Report; interpretation: Interpretation }>(`/admin/reports/${id}/review-issues/bulk-accept`, { method: "POST" }),
  parse: (id: string) => request<Report>(`/admin/reports/${id}/parse`, { method: "POST" }),
  patch: (id: string, changes: object) => request<Report>(`/admin/reports/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }),
  ready: (id: string) => request<Report>(`/admin/reports/${id}/ready`, { method: "POST" }),
  publish: (id: string, confirmWarnings = false, warningNote = "") => request<Report>(`/admin/reports/${id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_warnings: confirmWarnings, warning_note: warningNote }) }),
  withdraw: (id: string, reason: string) => request<Report>(`/admin/reports/${id}/withdraw`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }),
  resolveTerm: (termId: string, sectorKey: string) => request(`/admin/unmapped-terms/${termId}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sector_key: sectorKey }) }),
  enhanceParse: (id: string) => request(`/admin/reports/${id}/enhance/parse`, { method: "POST" }),
  patchPath: (reportId: string, entryId: string, changes: object) => request(`/admin/reports/${reportId}/path-entries/${entryId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }),
  patchAssessment: (reportId: string, assessmentId: string, changes: object) => request(`/admin/reports/${reportId}/sector-assessments/${assessmentId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }),
  bindMarketDate: (reportId: string, marketAsOfDate: string) => request(`/admin/reports/${reportId}/market-binding`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ market_as_of_date: marketAsOfDate, confirmed: true }) }),
  freezeMarketSnapshot: (reportId: string) => request(`/admin/reports/${reportId}/market-snapshot`, { method: "POST" }),
  enhancedReady: (reportId: string) => request(`/admin/reports/${reportId}/enhanced-ready`, { method: "POST" }),
  marketSummary: () => request<Record<string, unknown>>("/admin/market/summary"),
  marketStatus: () => request<Record<string, unknown>>("/market/status"),
  intradayStatus: () => request<IntradayStatus>("/market/intraday/status"),
  intradaySectors: () => request<Array<{ sector_key: string; sector_name: string; data_status: string; snapshot: unknown }>>("/market/intraday/sectors"),
  startIntraday: () => request<IntradayStatus>("/admin/market/intraday/start", { method: "POST" }),
  pauseIntraday: () => request<IntradayStatus>("/admin/market/intraday/pause", { method: "POST" }),
  refreshIntradayNow: () => request<Record<string, unknown>>("/admin/market/intraday/refresh-now", { method: "POST" }),
  marketRefreshRuns: () => request<Array<Record<string, unknown>>>("/admin/market/refresh-runs"),
  marketRefreshRun: (runId: string) => request<Record<string, unknown>>(`/admin/market/refresh-runs/${runId}`),
  pinSector: (key: string) => request(`/admin/sectors/${key}/pin`, { method: "POST" }),
  unpinSector: (key: string) => request<void>(`/admin/sectors/${key}/pin`, { method: "DELETE" }),
  refreshRealMarket: (asOfDate: string, sectorKeys?: string[]) => request<Record<string, unknown>>("/admin/market/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "manual_real_refresh", confirmed_research_only: true, as_of_date: asOfDate, sector_keys: sectorKeys }) }),
  importMarket: (file: File, confirmed: boolean) => { const body = new FormData(); body.append("file", file); body.append("confirmed", String(confirmed)); return request<Record<string, unknown>>("/admin/market/import", { method: "POST", body }); },
  specifications: () => request<Array<Record<string, unknown>>>("/admin/specifications"),
  uploadSpecification: (file: File, name: string, version: string, effectiveDate: string, note: string) => { const body = new FormData(); body.append("file", file); body.append("specification_name", name); body.append("version", version); if (effectiveDate) body.append("effective_date", effectiveDate); body.append("note", note); return request<Record<string, unknown>>("/admin/specifications", { method: "POST", body }); },
  setCurrentSpecification: (id: string) => request(`/admin/specifications/${id}/set-current`, { method: "POST" }),
  pdfPreview: (reportId: string) => request<{ page_count: number; page_urls: string[]; render_mode: string }>(`/reports/${reportId}/pdf/preview`),
  refreshFixtureMarket: (sectorKeys?: string[]) => request<Record<string, unknown>>("/admin/market/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "controlled_fixture", confirmed_research_only: true, sector_keys: sectorKeys }) }),
};
