import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "./routes/router";
import { IslandShell } from "./components/island/IslandShell";
import { RequireAdmin } from "./routes/RequireAdmin";

const HomePage = lazy(() => import("./pages/HomePage").then(module => ({ default: module.HomePage })));
const AdminLoginPage = lazy(() => import("./pages/LoginPage").then(module => ({ default: module.AdminLoginPage })));
const ReportDetailPage = lazy(() => import("./pages/ReportDetailPage").then(module => ({ default: module.ReportDetailPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then(module => ({ default: module.ReportsPage })));
const SectorDetailPage = lazy(() => import("./pages/SectorDetailPage").then(module => ({ default: module.SectorDetailPage })));
const SectorsPage = lazy(() => import("./pages/SectorsPage").then(module => ({ default: module.SectorsPage })));
const AboutPage = lazy(() => import("./pages/AboutPage").then(module => ({ default: module.AboutPage })));
const MarketLabPage = lazy(() => import("./pages/MarketLabPage").then(module => ({ default: module.MarketLabPage })));
const AdminDashboardPage = lazy(() => import("./pages/admin/AdminDashboardPage").then(module => ({ default: module.AdminDashboardPage })));
const AdminNewReportPage = lazy(() => import("./pages/admin/AdminNewReportPage").then(module => ({ default: module.AdminNewReportPage })));
const AdminReportsPage = lazy(() => import("./pages/admin/AdminReportsPage").then(module => ({ default: module.AdminReportsPage })));
const AdminReviewPage = lazy(() => import("./pages/admin/AdminReviewPage").then(module => ({ default: module.AdminReviewPage })));
const AdminMarketPage = lazy(() => import("./pages/admin/AdminMarketPage").then(module => ({ default: module.AdminMarketPage })));
const AdminInterpretationPage = lazy(() => import("./pages/admin/AdminInterpretationPage").then(module => ({ default: module.AdminInterpretationPage })));
const AdminSpecificationsPage = lazy(() => import("./pages/admin/AdminSpecificationsPage").then(module => ({ default: module.AdminSpecificationsPage })));

export function App() {
  return <IslandShell><Suspense fallback={<p role="status">页面加载中…</p>}><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/market-lab" element={<MarketLabPage />} />
    <Route path="/login" element={<Navigate to="/admin/login" replace />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/reports" element={<ReportsPage />} />
    <Route path="/reports/:reportId" element={<ReportDetailPage />} />
    <Route path="/sectors" element={<SectorsPage />} />
    <Route path="/sectors/:sectorKey" element={<SectorDetailPage />} />
    <Route path="/admin/login" element={<AdminLoginPage />} />
    <Route path="/admin" element={<RequireAdmin><AdminDashboardPage /></RequireAdmin>} />
    <Route path="/admin/market" element={<RequireAdmin><AdminMarketPage /></RequireAdmin>} />
    <Route path="/admin/specifications" element={<RequireAdmin><AdminSpecificationsPage /></RequireAdmin>} />
    <Route path="/admin/reports" element={<RequireAdmin><AdminReportsPage /></RequireAdmin>} />
    <Route path="/admin/reports/new" element={<RequireAdmin><AdminNewReportPage /></RequireAdmin>} />
    <Route path="/admin/reports/:reportId/interpretation" element={<RequireAdmin><AdminInterpretationPage /></RequireAdmin>} />
    <Route path="/admin/reports/:reportId/review" element={<RequireAdmin><AdminReviewPage /></RequireAdmin>} />
  </Routes></Suspense></IslandShell>;
}
