import { Navigate, Route, Routes } from "./routes/router";
import { IslandShell } from "./components/island/IslandShell";
import { HomePage } from "./pages/HomePage";
import { AdminLoginPage } from "./pages/LoginPage";
import { ReportDetailPage } from "./pages/ReportDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SectorDetailPage } from "./pages/SectorDetailPage";
import { SectorsPage } from "./pages/SectorsPage";
import { AdminDashboardPage } from "./pages/admin/AdminDashboardPage";
import { AdminNewReportPage } from "./pages/admin/AdminNewReportPage";
import { AdminReportsPage } from "./pages/admin/AdminReportsPage";
import { AdminReviewPage } from "./pages/admin/AdminReviewPage";
import { AdminMarketPage } from "./pages/admin/AdminMarketPage";
import { AdminInterpretationPage } from "./pages/admin/AdminInterpretationPage";
import { AdminSpecificationsPage } from "./pages/admin/AdminSpecificationsPage";
import { AboutPage } from "./pages/AboutPage";
import { MarketLabPage } from "./pages/MarketLabPage";
import { RequireAdmin } from "./routes/RequireAdmin";

export function App() { return <IslandShell><Routes><Route path="/" element={<HomePage />} /><Route path="/market-lab" element={<MarketLabPage />} /><Route path="/login" element={<Navigate to="/admin/login" replace />} /><Route path="/about" element={<AboutPage />} /><Route path="/reports" element={<ReportsPage />} /><Route path="/reports/:reportId" element={<ReportDetailPage />} /><Route path="/sectors" element={<SectorsPage />} /><Route path="/sectors/:sectorKey" element={<SectorDetailPage />} /><Route path="/admin/login" element={<AdminLoginPage />} /><Route path="/admin" element={<RequireAdmin><AdminDashboardPage /></RequireAdmin>} /><Route path="/admin/market" element={<RequireAdmin><AdminMarketPage /></RequireAdmin>} /><Route path="/admin/specifications" element={<RequireAdmin><AdminSpecificationsPage /></RequireAdmin>} /><Route path="/admin/reports" element={<RequireAdmin><AdminReportsPage /></RequireAdmin>} /><Route path="/admin/reports/new" element={<RequireAdmin><AdminNewReportPage /></RequireAdmin>} /><Route path="/admin/reports/:reportId/interpretation" element={<RequireAdmin><AdminInterpretationPage /></RequireAdmin>} /><Route path="/admin/reports/:reportId/review" element={<RequireAdmin><AdminReviewPage /></RequireAdmin>} /></Routes></IslandShell>; }
