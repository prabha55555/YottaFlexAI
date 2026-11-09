import { Download, RefreshCw, ScanSearch, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api/client";
import type { Anomaly, Page } from "../api/types";
import { useApi, useFacility, useToast } from "../components/hooks";
import { Card, EmptyState, ErrorState, fmt, KeyValue, Loading, Modal, PageHeader, Pagination, SeverityBadge, StatusPill } from "../components/ui";

interface AnomalyStats {
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  by_rule: Record<string, number>;
  by_facility: Record<string, number>;
}

const TYPES = ["LEAK", "BLOCKAGE", "PUMP_DEGRADATION", "SENSOR_FAULT", "TANK_OVERCAPACITY", "ABNORMAL_FLOW", "ABNORMAL_PRESSURE", "ABNORMAL_LEVEL", "MASS_BALANCE"];
const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const CATEGORIES = ["PROCESS", "SENSOR", "OPERATIONAL"];
const LIMIT = 25;

function num(v: number | null, unit: string) {
  if (v === null || v === undefined) return <span className="text-ink-3">—</span>;
  return (
    <span className="num">
      {fmt.n(v, 2)}
      {unit && <span className="text-ink-3"> {unit}</span>}
    </span>
  );
}

function renderEvidence(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmt.n(v, 3);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function AnomalyDetail({ anomaly }: { anomaly: Anomaly }) {
  const a = anomaly;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={a.severity} />
        <StatusPill status={a.category === "SENSOR" ? "SUSPECT" : a.category === "OPERATIONAL" ? "WARNING" : "CRITICAL"}>{a.category}</StatusPill>
        <span className="text-sm font-semibold">{fmt.label(a.anomaly_type)}</span>
        <span className="text-xs text-ink-2">{a.source === "SIMULATION" ? "Simulation" : "Telemetry scan"}</span>
      </div>
      <KeyValue
        items={[
          ["Anomaly ID", <span className="font-mono">{a.id}</span>],
          ["Facility", a.facility_id],
          ["Equipment", `${a.equipment_type} ${a.equipment_id}`],
          ["Sensor", a.sensor_id ?? "—"],
          ["Detected at", fmt.dt(a.detected_at)],
          ["Condition window", `${fmt.dt(a.start_time)} → ${fmt.dt(a.end_time)}`],
          ["Observed", num(a.observed_value, a.unit)],
          ["Expected", num(a.expected_value, a.unit)],
          ["Threshold", num(a.threshold, a.unit)],
          ["Simulation", a.simulation_id ? <Link className="text-brand-600 hover:underline" to={`/simulation?id=${a.simulation_id}`}>{a.simulation_id}</Link> : "—"],
        ]}
      />
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Detection rule</h3>
        <div className="rounded-md border border-line bg-stone-50 p-3 text-sm">
          <div className="font-mono text-xs text-brand-700">{a.detection_rule}</div>
          <div className="mt-1">{a.rule_description || "—"}</div>
        </div>
      </div>
      {a.evidence && Object.keys(a.evidence).length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Evidence</h3>
          <table className="table">
            <tbody>
              {Object.entries(a.evidence).map(([k, v]) => (
                <tr key={k}>
                  <td className="w-1/2 text-ink-2">{fmt.label(k)}</td>
                  <td className="num break-all">{renderEvidence(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Recommended action</h3>
        <p className="rounded-md border border-brand-100 bg-brand-50 p-3 text-sm">{a.recommended_action || "—"}</p>
      </div>
    </div>
  );
}

export default function Anomalies() {
  const { facilityId } = useFacility();
  const { notify } = useToast();
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [source, setSource] = useState("TELEMETRY_SCAN");
  const [equipment, setEquipment] = useState("");
  const [equipmentQuery, setEquipmentQuery] = useState("");
  const [skip, setSkip] = useState(0);
  const [selected, setSelected] = useState<Anomaly | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => setSkip(0), [type, severity, category, source, equipmentQuery, facilityId]);

  const params = {
    facility_id: facilityId,
    anomaly_type: type,
    severity,
    category,
    source,
    equipment_id: equipmentQuery,
  };
  const list = useApi(() => api.get<Page<Anomaly>>("/anomalies", { ...params, skip, limit: LIMIT }), [JSON.stringify(params), skip]);
  const stats = useApi(() => api.get<AnomalyStats>("/anomalies/stats", { facility_id: facilityId, source }), [facilityId, source]);

  const runScan = async () => {
    setScanning(true);
    try {
      const res = await api.post<Record<string, { detected: number; new: number; timestamps: number }>>("/anomalies/scan", undefined, { facility_id: facilityId });
      const parts = Object.entries(res).map(([f, r]) => `${f}: ${r.detected} detected, ${r.new} new`);
      notify("success", `Detection scan complete — ${parts.join("; ")}`);
      list.reload();
      stats.reload();
    } catch (e) {
      notify("error", `Scan failed: ${(e as Error).message}`);
    } finally {
      setScanning(false);
    }
  };

  const chip = (label: string, count: number, active: boolean, onClick: () => void) => (
    <button
      key={label}
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-xs font-medium num ${active ? "border-brand-500 bg-brand-50 text-brand-700" : "border-line bg-white text-ink-2 hover:bg-stone-50"}`}
    >
      {fmt.label(label)} <span className="ml-1 font-semibold text-ink">{count}</span>
    </button>
  );

  return (
    <div>
      <PageHeader
        title="Anomaly Detection"
        subtitle="Rule-based, explainable detections over simulated telemetry and simulation runs. Ground truth is never used as detector input."
        actions={
          <>
            <button className="btn-secondary" onClick={() => download("/anomalies/export", { ...params, format: "csv" })}>
              <Download size={14} /> CSV
            </button>
            <button className="btn-secondary" onClick={() => download("/anomalies/export", { ...params, format: "json" })}>
              <Download size={14} /> JSON
            </button>
            <button className="btn-secondary" onClick={() => { list.reload(); stats.reload(); }} aria-label="Refresh">
              <RefreshCw size={14} /> Refresh
            </button>
            <button className="btn-primary" onClick={runScan} disabled={scanning}>
              <ScanSearch size={14} /> {scanning ? "Scanning…" : `Run detection scan${facilityId ? ` (${facilityId})` : ""}`}
            </button>
          </>
        }
      />

      <Card className="mb-4" title="Distribution" subtitle="Click a chip to filter. Counts reflect the selected source and facility scope.">
        {stats.error ? (
          <ErrorState error={stats.error} onRetry={stats.reload} />
        ) : !stats.data ? (
          <Loading />
        ) : Object.keys(stats.data.by_type).length === 0 ? (
          <EmptyState title="No anomalies recorded" hint="Run a detection scan or a simulation." />
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-16 text-xs font-medium text-ink-2">Type</span>
              {Object.entries(stats.data.by_type).sort((a, b) => b[1] - a[1]).map(([k, v]) => chip(k, v, type === k, () => setType(type === k ? "" : k)))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-16 text-xs font-medium text-ink-2">Severity</span>
              {SEVERITIES.filter((s) => stats.data!.by_severity[s]).map((s) => chip(s, stats.data!.by_severity[s], severity === s, () => setSeverity(severity === s ? "" : s)))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-16 text-xs font-medium text-ink-2">Category</span>
              {Object.entries(stats.data.by_category).map(([k, v]) => chip(k, v, category === k, () => setCategory(category === k ? "" : k)))}
            </div>
          </div>
        )}
      </Card>

      <Card bodyClass="p-0">
        <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
          <label className="w-44">
            <span className="label">Type</span>
            <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {TYPES.map((t) => <option key={t} value={t}>{fmt.label(t)}</option>)}
            </select>
          </label>
          <label className="w-32">
            <span className="label">Severity</span>
            <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">All</option>
              {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="w-36">
            <span className="label">Category</span>
            <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All</option>
              {CATEGORIES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="w-40">
            <span className="label">Source</span>
            <select className="input" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="TELEMETRY_SCAN">Telemetry scan</option>
              <option value="SIMULATION">Simulation</option>
              <option value="">All sources</option>
            </select>
          </label>
          <form className="flex items-end gap-1" onSubmit={(e) => { e.preventDefault(); setEquipmentQuery(equipment.trim().toUpperCase()); }}>
            <label className="w-44">
              <span className="label">Equipment / sensor ID</span>
              <input className="input" placeholder="e.g. PIPE-005" value={equipment} onChange={(e) => setEquipment(e.target.value)} />
            </label>
            <button className="btn-secondary" type="submit"><Search size={14} /> Find</button>
            {equipmentQuery && <button type="button" className="btn-ghost" onClick={() => { setEquipment(""); setEquipmentQuery(""); }}>Clear</button>}
          </form>
        </div>
        {list.error ? (
          <div className="p-4"><ErrorState error={list.error} onRetry={list.reload} /></div>
        ) : !list.data ? (
          <Loading />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No anomalies match the filters" hint="Adjust filters or run a detection scan." />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th><th>Detected</th><th>Facility</th><th>Equipment</th><th>Type</th><th>Category</th>
                  <th>Severity</th><th>Rule</th><th className="text-right">Observed</th><th className="text-right">Expected</th><th className="text-right">Threshold</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id} className="cursor-pointer" onClick={() => setSelected(a)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(a)}>
                    <td className="font-mono text-xs">{a.id}</td>
                    <td className="whitespace-nowrap num">{fmt.dt(a.detected_at)}</td>
                    <td>{a.facility_id}</td>
                    <td className="whitespace-nowrap">
                      {a.equipment_id}
                      {a.sensor_id && <div className="text-xs text-ink-2">{a.sensor_id}</div>}
                    </td>
                    <td className="whitespace-nowrap">{fmt.label(a.anomaly_type)}</td>
                    <td className="text-xs">{a.category}</td>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td className="font-mono text-xs">{a.detection_rule}</td>
                    <td className="text-right whitespace-nowrap">{num(a.observed_value, a.unit)}</td>
                    <td className="text-right whitespace-nowrap">{num(a.expected_value, a.unit)}</td>
                    <td className="text-right whitespace-nowrap">{num(a.threshold, a.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && <Pagination skip={skip} limit={LIMIT} total={list.data.total} onChange={setSkip} />}
      </Card>

      <Modal open={!!selected} title={selected ? `${selected.id} · ${fmt.label(selected.anomaly_type)}` : ""} onClose={() => setSelected(null)} wide>
        {selected && <AnomalyDetail anomaly={selected} />}
      </Modal>
    </div>
  );
}
