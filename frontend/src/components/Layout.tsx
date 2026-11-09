import {
  Activity, AlertTriangle, BarChart3, Bell, Boxes, Building2, Cpu, Database, FlaskConical, Gauge, GitFork,
  LayoutDashboard, Menu, Radio, ShieldCheck, Waves, Workflow, X,
} from "lucide-react";
import { ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useApi, useFacility } from "./hooks";
import { SimulatedBadge } from "./ui";

const NAV: { group: string; items: { to: string; label: string; icon: typeof Gauge }[] }[] = [
  { group: "Operations", items: [
    { to: "/", label: "Dashboard", icon: LayoutDashboard },
    { to: "/monitoring", label: "Live Monitoring", icon: Radio },
    { to: "/topology", label: "Plant Topology", icon: Workflow },
    { to: "/alarms", label: "Alarm Management", icon: Bell },
    { to: "/anomalies", label: "Anomaly Detection", icon: AlertTriangle },
  ] },
  { group: "Engineering", items: [
    { to: "/simulation", label: "Simulation Studio", icon: FlaskConical },
    { to: "/analytics", label: "Analytics", icon: BarChart3 },
    { to: "/validation", label: "Data Validation", icon: ShieldCheck },
  ] },
  { group: "Master Data", items: [
    { to: "/facilities", label: "Facilities", icon: Building2 },
    { to: "/equipment/pumps", label: "Pumps", icon: Cpu },
    { to: "/equipment/tanks", label: "Tanks", icon: Database },
    { to: "/equipment/valves", label: "Valves", icon: GitFork },
    { to: "/equipment/pipes", label: "Pipes", icon: Waves },
    { to: "/equipment/sensors", label: "Sensors", icon: Activity },
  ] },
];

const SINGLE_FACILITY_PAGES = ["/topology", "/monitoring", "/simulation", "/analytics"];

export default function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { facilities, facilityId, setFacilityId, concreteId } = useFacility();
  const loc = useLocation();
  const needsOne = SINGLE_FACILITY_PAGES.some((p) => loc.pathname.startsWith(p));
  const alarms = useApi(() => api.get<{ open_by_severity: Record<string, number> }>("/alarms/stats", { source: "LIVE" }), [loc.pathname]);
  const openAlarms = Object.values(alarms.data?.open_by_severity ?? {}).reduce((a, b) => a + b, 0);
  const critical = alarms.data?.open_by_severity?.CRITICAL ?? 0;

  return (
    <div className="flex h-full">
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-60 shrink-0 transform border-r border-line bg-[#f5f4f1] transition-transform lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex h-14 items-center gap-2 border-b border-line px-4">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-brand-600 text-white">
            <Boxes size={18} />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">YottaFlex</div>
            <div className="text-[11px] text-ink-2">Process Monitoring</div>
          </div>
          <button className="ml-auto lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X size={18} />
          </button>
        </div>
        <nav className="h-[calc(100%-3.5rem)] overflow-y-auto px-2 py-3">
          {NAV.map((g) => (
            <div key={g.group} className="mb-4">
              <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">{g.group}</div>
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.to === "/"}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-white font-medium text-brand-700 shadow-sm ring-1 ring-line" : "text-ink-2 hover:bg-white/70 hover:text-ink"}`
                  }
                >
                  <it.icon size={16} />
                  <span className="flex-1">{it.label}</span>
                  {it.to === "/alarms" && openAlarms > 0 && (
                    <span className={`rounded-full px-1.5 text-[11px] font-semibold num ${critical ? "bg-critical text-white" : "bg-amber-200 text-amber-900"}`}>{openAlarms}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/20 lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-white/90 px-4 backdrop-blur">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <label className="flex items-center gap-2 text-sm">
            <Building2 size={16} className="text-ink-2" />
            <span className="sr-only">Facility</span>
            <select className="input w-auto py-1" value={needsOne ? concreteId : facilityId} onChange={(e) => setFacilityId(e.target.value)}>
              {!needsOne && <option value="">All facilities</option>}
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.id} · {f.name}
                </option>
              ))}
            </select>
          </label>
          <div className="ml-auto flex items-center gap-3">
            <SimulatedBadge />
            <NavLink to="/alarms" className="relative text-ink-2 hover:text-ink" aria-label={`${openAlarms} open alarms`}>
              <Bell size={18} />
              {openAlarms > 0 && (
                <span className={`absolute -right-2 -top-1.5 rounded-full px-1 text-[10px] font-bold num ${critical ? "bg-critical text-white" : "bg-warning text-ink"}`}>{openAlarms}</span>
              )}
            </NavLink>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
