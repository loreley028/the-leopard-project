import type { Principal, Report, Sector } from "../types";

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
  sectors: () => request<Sector[]>("/sectors"),
  sector: (key: string) => request<Sector>(`/sectors/${key}`),
  adminSummary: () => request<Record<string, number>>("/admin/summary"),
  adminReports: () => request<Report[]>("/admin/reports"),
  adminReport: (id: string) => request<Report>(`/admin/reports/${id}`),
  upload: (file: File) => { const body = new FormData(); body.append("file", file); return request<{ report: Report; duplicate: boolean }>("/admin/reports", { method: "POST", body }); },
  parse: (id: string) => request<Report>(`/admin/reports/${id}/parse`, { method: "POST" }),
  patch: (id: string, changes: object) => request<Report>(`/admin/reports/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }),
  ready: (id: string) => request<Report>(`/admin/reports/${id}/ready`, { method: "POST" }),
  publish: (id: string) => request<Report>(`/admin/reports/${id}/publish`, { method: "POST" }),
  withdraw: (id: string, reason: string) => request<Report>(`/admin/reports/${id}/withdraw`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }),
  resolveTerm: (termId: string, sectorKey: string) => request(`/admin/unmapped-terms/${termId}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sector_key: sectorKey }) }),
};
