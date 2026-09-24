import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import { applyLimits } from "./kpi/kpiConfig";
import AuditOversight from "./pages/AuditOversight";
import Dashboard from "./pages/Dashboard";
import KpiDetail from "./pages/KpiDetail";
import Login from "./pages/Login";
import Performance from "./pages/Performance";
import Portfolio from "./pages/Portfolio";
import Reconciliation from "./pages/Reconciliation";
import ReportView from "./pages/ReportView";
import Reports from "./pages/Reports";
import Scenario from "./pages/Scenario";
import Tasks from "./pages/Tasks";

// Thresholds come from the database once per session (specs/breach-levels.md); if they can't be
// loaded the built-in values in kpiConfig stay, so a failure never blocks the app.
let limitsLoaded = null;
function loadLimitsOnce() {
  if (!limitsLoaded) {
    limitsLoaded = Promise.resolve()
      .then(() => api.kpiLimits())
      .then(applyLimits)
      .catch(() => {});
  }
  return limitsLoaded;
}

function RequireAuth({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (user) loadLimitsOnce().then(() => setReady(true));
  }, [user]);
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return ready ? children : null;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/kpi/:key" element={<RequireAuth><KpiDetail /></RequireAuth>} />
      <Route path="/portfolio" element={<RequireAuth><Portfolio /></RequireAuth>} />
      <Route path="/scenario" element={<RequireAuth><Scenario /></RequireAuth>} />
      <Route path="/performance" element={<RequireAuth><Performance /></RequireAuth>} />
      <Route path="/reports" element={<RequireAuth><Reports /></RequireAuth>} />
      <Route path="/reports/:id" element={<RequireAuth><ReportView /></RequireAuth>} />
      <Route path="/tasks" element={<RequireAuth><Tasks /></RequireAuth>} />
      <Route path="/audit-oversight" element={<RequireAuth><AuditOversight /></RequireAuth>} />
      <Route path="/reconciliation" element={<RequireAuth><Reconciliation /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
