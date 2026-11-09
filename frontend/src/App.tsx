import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";

// Route-level code splitting keeps the initial bundle small (React Flow / Recharts load on demand).
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Monitoring = lazy(() => import("./pages/Monitoring"));
const Topology = lazy(() => import("./pages/Topology"));
const Alarms = lazy(() => import("./pages/Alarms"));
const Anomalies = lazy(() => import("./pages/Anomalies"));
const SimulationStudio = lazy(() => import("./pages/SimulationStudio"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Validation = lazy(() => import("./pages/Validation"));
const Facilities = lazy(() => import("./pages/Facilities"));
const Equipment = lazy(() => import("./pages/Equipment"));

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<Loading label="Loading page…" />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/topology" element={<Topology />} />
          <Route path="/alarms" element={<Alarms />} />
          <Route path="/anomalies" element={<Anomalies />} />
          <Route path="/simulation" element={<SimulationStudio />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/validation" element={<Validation />} />
          <Route path="/facilities" element={<Facilities />} />
          <Route path="/equipment/:kind" element={<Equipment />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
