import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Performance from "./pages/Performance";
import Portfolio from "./pages/Portfolio";
import ReportView from "./pages/ReportView";
import Reports from "./pages/Reports";
import Scenario from "./pages/Scenario";
import Workflow from "./pages/Workflow";

function RequireAuth({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/portfolio" element={<RequireAuth><Portfolio /></RequireAuth>} />
      <Route path="/scenario" element={<RequireAuth><Scenario /></RequireAuth>} />
      <Route path="/performance" element={<RequireAuth><Performance /></RequireAuth>} />
      <Route path="/reports" element={<RequireAuth><Reports /></RequireAuth>} />
      <Route path="/reports/:id" element={<RequireAuth><ReportView /></RequireAuth>} />
      <Route path="/workflow" element={<RequireAuth><Workflow /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
