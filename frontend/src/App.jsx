import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";

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
      <Route path="/portfolio" element={<RequireAuth><Placeholder screen="Screen 2 — Portfolio & Credit Risk" /></RequireAuth>} />
      <Route path="/scenario" element={<RequireAuth><Placeholder screen="Screen 4 — Scenario Modelling" /></RequireAuth>} />
      <Route path="/performance" element={<RequireAuth><Placeholder screen="Screen 5 — Branch & Segment Performance" /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
