import { Download, FlaskConical, GitCompare, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { ApiError, api, download } from "../api/client";
import type {
  Anomaly, Comparison, OperatingMode, Page, Pipe, Pump, ScenarioInfo, Sensor, SimulationDetail, SimulationListItem,
  SimulationParameters, Tank, Valve,
} from "../api/types";
import { axisProps, ChartBox, ChartLegend, ChartTooltip, Grid, SERIES, STATUS, TimeAxis, ValueAxis, zipSeries } from "../components/charts";
import { useApi, useFacility, useToast } from "../components/hooks";
import {
  Card, EmptyState, ErrorState, Field, fmt, Loading, Modal, PageHeader, Pagination, SeverityBadge, Stat, StatusPill,
} from "../components/ui";
import { AnomalyDetail } from "./Anomalies";

// ------------------------------------------------------------ local types
type MapKey = "pump_speeds" | "pump_availability" | "pump_health" | "valve_openings" | "tank_initial_levels" |
  "flow_demand" | "pipe_restrictions" | "pipe_leaks" | "sensor_faults";
type Option = { id: string; label: string };
type OverrideSpec = {
  key: MapKey; title: string; hint: string; kind: "number" | "bool" | "mode";
  min?: number; max?: number; step?: number; unit?: string; def: number | boolean | string; options: Option[];
};
const FAULT_MODES = ["FLATLINE", "SPIKE", "OUT_OF_RANGE", "MISSING", "BIAS"];
const STEP_MINUTES = [5, 10, 15, 30, 60];
const HIST_LIMIT = 10;

interface Equipment { pumps: Pump[]; valves: Valve[]; tanks: Tank[]; pipes: Pipe[]; sensors: Sensor[] }

function useEquipment(facilityId: string) {
  return useApi<Equipment>(async () => {
    const q = { facility_id: facilityId, limit: 1000 };
    const [p, v, t, pi, s] = await Promise.all([
      api.get<Page<Pump>>("/pumps", q), api.get<Page<Valve>>("/valves", q), api.get<Page<Tank>>("/tanks", q),
      api.get<Page<Pipe>>("/pipes", q), api.get<Page<Sensor>>("/sensors", q),
    ]);
    return { pumps: p.items, valves: v.items, tanks: t.items, pipes: pi.items, sensors: s.items };
  }, [facilityId]);
}

function overrideSpecs(eq: Equipment): OverrideSpec[] {
  const pumps = eq.pumps.map((p) => ({ id: p.id, label: `${p.id} · ${p.name}` }));
  const sensored = new Set(eq.sensors.filter((s) => s.equipment_type === "PIPE").map((s) => s.equipment_id));
  const pipes = eq.pipes.filter((p) => sensored.has(p.id) || /transfer/i.test(p.name)).map((p) => ({ id: p.id, label: `${p.id} · ${p.name}` }));
  return [
    { key: "pump_speeds", title: "Pump speed", hint: "0–110 % of rated speed", kind: "number", min: 0, max: 110, step: 1, unit: "%", def: 100, options: pumps },
    { key: "pump_availability", title: "Pump availability", hint: "Unavailable pumps deliver no flow", kind: "bool", def: false, options: pumps },
    { key: "pump_health", title: "Pump health (degradation fault)", hint: "0.3–1.0; hidden from detector", kind: "number", min: 0.3, max: 1, step: 0.01, def: 0.8, options: pumps },
    { key: "valve_openings", title: "Valve opening", hint: "0 % = closed", kind: "number", min: 0, max: 100, step: 1, unit: "%", def: 50, options: eq.valves.map((v) => ({ id: v.id, label: `${v.id} · ${v.name} (${v.role})` })) },
    { key: "tank_initial_levels", title: "Tank initial level", hint: "0–100 % of capacity", kind: "number", min: 0, max: 100, step: 1, unit: "%", def: 50, options: eq.tanks.map((t) => ({ id: t.id, label: `${t.id} · ${t.name}` })) },
    { key: "flow_demand", title: "Outlet flow demand", hint: "Nominal consumer demand (≤ 3× design)", kind: "number", min: 0, step: 1, unit: "m³/h", def: 100,
      options: eq.valves.filter((v) => v.role === "OUTLET").map((v) => ({ id: v.id, label: `${v.id} · ${v.name} (nominal ${fmt.n(v.boundary_flow_m3h)} m³/h)` })) },
    { key: "pipe_restrictions", title: "Pipe restriction (blockage fault)", hint: "0–95 % flow-area loss; hidden from detector", kind: "number", min: 0, max: 95, step: 1, unit: "%", def: 50, options: pipes },
    { key: "pipe_leaks", title: "Pipe leak (fault)", hint: "Fraction of line flow lost, 0–0.5", kind: "number", min: 0, max: 0.5, step: 0.01, def: 0.1, options: pipes },
    { key: "sensor_faults", title: "Sensor faults", hint: "Instrument fault mode", kind: "mode", def: "BIAS",
      options: eq.sensors.map((s) => ({ id: s.id, label: `${s.id} · ${s.tag} (${s.sensor_type} @ ${s.equipment_id})` })) },
  ];
}

// ------------------------------------------------------------ override editor
function OverrideEditor({ spec, value, onChange, errors }: {
  spec: OverrideSpec; value: Record<string, number | boolean | string> | undefined;
  onChange: (v: Record<string, number | boolean | string> | undefined) => void; errors: Record<string, string>;
}) {
  const [pick, setPick] = useState("");
  const entries = Object.entries(value ?? {});
  const available = spec.options.filter((o) => !(value && o.id in value));
  const set = (id: string, v: number | boolean | string) => onChange({ ...(value ?? {}), [id]: v });
  const remove = (id: string) => {
    const n = { ...(value ?? {}) };
    delete n[id];
    onChange(Object.keys(n).length ? n : undefined);
  };
  if (!spec.options.length) return null;
  return (
    <div className="rounded-md border border-line">
      <div className="flex items-center justify-between gap-2 border-b border-line bg-stone-50 px-2.5 py-1.5">
        <div>
          <div className="text-xs font-semibold">{spec.title}</div>
          <div className="text-[11px] text-ink-3">{spec.hint}</div>
        </div>
        <div className="flex items-center gap-1">
          <select className="input w-40 py-1 text-xs" value={pick} onChange={(e) => setPick(e.target.value)} aria-label={`Add ${spec.title} override`}>
            <option value="">Select…</option>
            {available.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
          <button className="btn-secondary px-2 py-1" disabled={!pick} onClick={() => { set(pick, spec.def); setPick(""); }} aria-label="Add override">
            <Plus size={13} />
          </button>
        </div>
      </div>
      {entries.length > 0 && (
        <div className="divide-y divide-stone-100">
          {entries.map(([id, v]) => {
            const err = errors[`${spec.key}.${id}`];
            return (
              <div key={id} className="px-2.5 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="w-24 font-mono text-xs">{id}</span>
                  {spec.kind === "bool" ? (
                    <select className="input py-1 text-xs" value={String(v)} onChange={(e) => set(id, e.target.value === "true")}>
                      <option value="true">Available</option>
                      <option value="false">Unavailable</option>
                    </select>
                  ) : spec.kind === "mode" ? (
                    <select className="input py-1 text-xs" value={String(v)} onChange={(e) => set(id, e.target.value)}>
                      {FAULT_MODES.map((m) => <option key={m}>{m}</option>)}
                    </select>
                  ) : (
                    <input type="number" className="input py-1 text-xs num" value={v as number} min={spec.min} max={spec.max} step={spec.step}
                      onChange={(e) => set(id, e.target.value === "" ? NaN : Number(e.target.value))} aria-label={`${spec.title} ${id}`} />
                  )}
                  {spec.unit && <span className="text-xs text-ink-2">{spec.unit}</span>}
                  <button className="btn-ghost px-1.5 py-1" onClick={() => remove(id)} aria-label={`Remove ${id}`}><Trash2 size={13} /></button>
                </div>
                {err && <div className="mt-0.5 text-[11px] text-critical">{err}</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function validate(p: SimulationParameters, specs: OverrideSpec[], s: { seed: string; steps: string; faultStart: string }) {
  const e: Record<string, string> = {};
  if (!/^-?\d+$/.test(s.seed)) e.seed = "Seed must be an integer";
  const steps = Number(s.steps);
  if (!Number.isInteger(steps) || steps < 8 || steps > 672) e.steps = "Steps must be an integer between 8 and 672";
  if (s.faultStart !== "") {
    const f = Number(s.faultStart);
    if (!Number.isInteger(f) || f < 0 || f >= steps) e.fault_start_step = "Must be an integer in [0, steps)";
  }
  if (p.demand_factor !== undefined && (Number.isNaN(p.demand_factor) || p.demand_factor < 0 || p.demand_factor > 3)) e.demand_factor = "Demand factor must be within 0–3";
  for (const spec of specs) {
    if (spec.kind !== "number") continue;
    for (const [id, v] of Object.entries((p[spec.key] as Record<string, number>) ?? {})) {
      if (typeof v !== "number" || Number.isNaN(v)) e[`${spec.key}.${id}`] = "Enter a number";
      else if ((spec.min !== undefined && v < spec.min) || (spec.max !== undefined && v > spec.max)) e[`${spec.key}.${id}`] = `Allowed range ${spec.min ?? "-∞"}–${spec.max ?? "∞"}`;
    }
  }
  return e;
}

// ------------------------------------------------------------ result panels
function Kpis({ run }: { run: SimulationDetail }) {
  const k = run.summary!.kpis;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Total inflow" value={fmt.n(k.total_inflow_m3, 0)} unit="m³" />
      <Stat label="Total outflow" value={fmt.n(k.total_outflow_m3, 0)} unit="m³" />
      <Stat label="Demand served" value={fmt.n(k.demand_served_pct, 1)} unit="%" tone={(k.demand_served_pct ?? 100) < 95 ? "warning" : "good"} />
      <Stat label="Storage change" value={fmt.n(k.storage_change_m3, 0)} unit="m³" />
      <Stat label="True leak volume" value={fmt.n(k.true_leak_m3, 1)} unit="m³" tone={k.true_leak_m3 > 0 ? "critical" : "default"} hint="Model truth (not visible to detector)" />
      <Stat label="Overflow" value={fmt.n(k.overflow_m3, 1)} unit="m³" tone={k.overflow_m3 > 0 ? "critical" : "default"} />
      <Stat label="Pump energy" value={fmt.n(k.pump_energy_kwh, 0)} unit="kWh" hint={`${fmt.n(k.specific_energy_kwh_per_m3, 3)} kWh/m³`} />
      <Stat label="Anomalies" value={k.anomaly_count} hint={`${k.critical_anomalies} critical`} tone={k.critical_anomalies ? "critical" : k.anomaly_count ? "warning" : "good"} />
    </div>
  );
}

function RunCharts({ run }: { run: SimulationDetail }) {
  const ts = run.timeseries!;
  const pumpIds = Object.keys(ts.lines);
  const tankIds = Object.keys(ts.tanks);
  const faultPump = Object.keys((run.modified_parameters?.resolved?.pump_health as object) ?? {})[0];
  const [pump, setPump] = useState(faultPump && pumpIds.includes(faultPump) ? faultPump : pumpIds[0] ?? "");
  const [tanks, setTanks] = useState<string[]>(() => {
    const ranked = [...tankIds].sort((a, b) => {
      const r = (t: string) => Math.abs((run.summary!.tanks[t]?.max_level_pct ?? 50) - 50) + Math.abs((run.summary!.tanks[t]?.min_level_pct ?? 50) - 50);
      return r(b) - r(a);
    });
    return ranked.slice(0, 3);
  });
  useEffect(() => {
    if (!pumpIds.includes(pump)) setPump(pumpIds[0] ?? "");
  }, [run.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const faultStart = run.modified_parameters?.fault_start_step;
  const hasFaults = ((run.effective_config?.injected_faults as unknown[]) ?? []).length > 0;
  const faultTs = hasFaults && faultStart !== undefined ? ts.timestamps[faultStart] : undefined;
  const line = ts.lines[pump];
  const flowRows = line ? zipSeries(ts.timestamps, { "Pump discharge flow": line.q_up, "Delivered flow": line.q_down }) : [];
  const pRows = line ? zipSeries(ts.timestamps, { "Discharge pressure": line.p_discharge, "Suction pressure": line.p_suction }) : [];
  const tankRows = zipSeries(ts.timestamps, Object.fromEntries(tanks.map((t) => [t, ts.tanks[t].level_pct])));
  const faultLine = faultTs ? <ReferenceLine x={faultTs} stroke="#52514e" strokeDasharray="4 3" label={{ value: "fault start", fill: "#52514e", fontSize: 10, position: "insideTopRight" }} /> : null;

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Pump line flow" subtitle="True simulated state (m³/h)" actions={
        <select className="input w-36 py-1 text-xs" value={pump} onChange={(e) => setPump(e.target.value)} aria-label="Pump">
          {pumpIds.map((p) => <option key={p}>{p}</option>)}
        </select>}>
        <ChartBox label={`Flow for ${pump}`}>
          <ResponsiveContainer>
            <LineChart data={flowRows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              {Grid({})}{TimeAxis({})}{ValueAxis({ unit: "m³/h" })}{ChartTooltip({ unit: "m³/h" })}{ChartLegend({})}
              {faultLine}
              <Line dataKey="Pump discharge flow" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="Delivered flow" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartBox>
      </Card>
      <Card title="Pump pressures" subtitle={`${pump} suction and discharge (bar g)`}>
        <ChartBox label={`Pressure for ${pump}`}>
          <ResponsiveContainer>
            <LineChart data={pRows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              {Grid({})}{TimeAxis({})}{ValueAxis({ unit: "bar" })}{ChartTooltip({ unit: "bar" })}{ChartLegend({})}
              {faultLine}
              <Line dataKey="Discharge pressure" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="Suction pressure" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartBox>
      </Card>
      <Card className="xl:col-span-2" title="Tank levels" subtitle="Select up to 4 tanks. Dashed line = 95 % high-level alarm." actions={
        <div className="flex flex-wrap gap-1">
          {tankIds.map((t) => {
            const on = tanks.includes(t);
            return (
              <button key={t} onClick={() => setTanks(on ? tanks.filter((x) => x !== t) : tanks.length < 4 ? [...tanks, t] : tanks)}
                disabled={!on && tanks.length >= 4}
                className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${on ? "border-brand-500 bg-brand-50 text-brand-700" : "border-line text-ink-2 disabled:opacity-40"}`}>
                {t}
              </button>
            );
          })}
        </div>}>
        {tanks.length === 0 ? <EmptyState title="Select at least one tank" /> : (
          <ChartBox label="Tank levels" height={260}>
            <ResponsiveContainer>
              <LineChart data={tankRows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                {Grid({})}{TimeAxis({})}{ValueAxis({ unit: "%", domain: [0, 100] })}{ChartTooltip({ unit: "%" })}{ChartLegend({})}
                <ReferenceLine y={95} stroke={STATUS.critical} strokeDasharray="5 4" />
                {faultLine}
                {tanks.map((t) => (
                  <Line key={t} dataKey={t} stroke={SERIES[tankIds.indexOf(t) % SERIES.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </ChartBox>
        )}
      </Card>
    </div>
  );
}

function RunAnomalies({ simId }: { simId: string }) {
  const res = useApi(() => api.get<Page<Anomaly>>("/anomalies", { simulation_id: simId, limit: 200 }), [simId]);
  const [sel, setSel] = useState<Anomaly | null>(null);
  return (
    <Card title="Detected anomalies" subtitle="Detector ran on simulated sensor readings with only the known operating setpoints" bodyClass="p-0"
      actions={<Link className="btn-secondary py-1 text-xs" to={`/alarms?simulation_id=${simId}`}>View alarms</Link>}>
      {res.error ? <div className="p-4"><ErrorState error={res.error} onRetry={res.reload} /></div> : !res.data ? <Loading /> :
        res.data.items.length === 0 ? <EmptyState title="No anomalies detected" hint="The run stayed within all detection thresholds." /> : (
          <div className="max-h-80 overflow-auto">
            <table className="table">
              <thead><tr><th>ID</th><th>Detected</th><th>Equipment</th><th>Type</th><th>Severity</th><th>Rule</th><th className="text-right">Observed</th><th className="text-right">Expected</th></tr></thead>
              <tbody>
                {res.data.items.map((a) => (
                  <tr key={a.id} className="cursor-pointer" onClick={() => setSel(a)}>
                    <td className="font-mono text-xs">{a.id}</td>
                    <td className="whitespace-nowrap num">{fmt.dt(a.detected_at)}</td>
                    <td>{a.equipment_id}{a.sensor_id && <div className="text-xs text-ink-2">{a.sensor_id}</div>}</td>
                    <td className="whitespace-nowrap">{fmt.label(a.anomaly_type)}</td>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td className="font-mono text-xs">{a.detection_rule}</td>
                    <td className="text-right num whitespace-nowrap">{fmt.n(a.observed_value, 2)} {a.unit}</td>
                    <td className="text-right num whitespace-nowrap">{a.expected_value === null ? "—" : `${fmt.n(a.expected_value, 2)} ${a.unit}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      <Modal open={!!sel} title={sel ? `${sel.id} · ${fmt.label(sel.anomaly_type)}` : ""} onClose={() => setSel(null)} wide>
        {sel && <AnomalyDetail anomaly={sel} />}
      </Modal>
    </Card>
  );
}

function MassBalancePanel({ run }: { run: SimulationDetail }) {
  const mb = run.mass_balance;
  if (!mb) return null;
  const m = mb.measured;
  const t = mb.true_closure;
  return (
    <Card title="Mass balance" subtitle="Measured (from simulated meters) vs. model truth">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StatusPill status={m.status} />
        <StatusPill status={m.classification} />
        <span className="text-sm num">Balance error {m.balance_error_pct === null ? "—" : `${fmt.n(m.balance_error_pct, 2)} %`} (tolerance {m.tolerance_pct} %)</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <table className="table">
          <thead><tr><th>Measured</th><th className="text-right">m³</th></tr></thead>
          <tbody>
            <tr><td>Total inflow</td><td className="text-right num">{fmt.n(m.total_inflow_m3, 1)}</td></tr>
            <tr><td>Total outflow</td><td className="text-right num">{fmt.n(m.total_outflow_m3, 1)}</td></tr>
            <tr><td>Storage change</td><td className="text-right num">{fmt.n(m.storage_change_m3, 1)}</td></tr>
            <tr><td>Residual</td><td className="text-right num font-semibold">{fmt.n(m.residual_m3, 1)}</td></tr>
            <tr><td>Estimated leakage</td><td className="text-right num">{fmt.n(m.estimated_leakage_m3, 1)}</td></tr>
          </tbody>
        </table>
        <table className="table">
          <thead><tr><th>Model truth</th><th className="text-right">m³</th></tr></thead>
          <tbody>
            {Object.entries(t).map(([k, v]) => (
              <tr key={k}><td>{fmt.label(k.replace(/_m3$/, ""))}</td><td className="text-right num">{fmt.n(v, 3)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {m.suspect_sensors.length > 0 && <p className="mt-2 text-xs text-ink-2">Suspect instruments on the balance boundary: {m.suspect_sensors.join(", ")}</p>}
    </Card>
  );
}

function AnomalyTypeChart({ byType }: { byType: Record<string, number> }) {
  const rows = Object.entries(byType).map(([k, v]) => ({ type: fmt.label(k), count: v }));
  if (!rows.length) return <EmptyState title="No anomalies" />;
  return (
    <ChartBox label="Anomalies by type" height={Math.max(120, rows.length * 30 + 30)}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
          <XAxis type="number" allowDecimals={false} {...axisProps} />
          <YAxis type="category" dataKey="type" width={130} {...axisProps} />
          {ChartTooltip({ timeLabel: false })}
          <Bar dataKey="count" name="Anomalies" fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function ComparePanel({ baselineId, modifiedId }: { baselineId: string; modifiedId: string }) {
  const cmp = useApi(() => api.get<Comparison>("/simulations/compare", { baseline_id: baselineId, modified_id: modifiedId }), [baselineId, modifiedId]);
  const [series, setSeries] = useState("");
  const c = cmp.data;
  const options = useMemo(() => {
    if (!c) return [];
    const o: { id: string; label: string; unit: string }[] = [];
    Object.keys(c.timeseries.modified.lines).forEach((p) => o.push({ id: `line:${p}:q_down`, label: `${p} delivered flow`, unit: "m³/h" }));
    Object.keys(c.timeseries.modified.lines).forEach((p) => o.push({ id: `line:${p}:p_discharge`, label: `${p} discharge pressure`, unit: "bar" }));
    Object.keys(c.timeseries.modified.tanks).forEach((t) => o.push({ id: `tank:${t}:level_pct`, label: `${t} level`, unit: "%" }));
    return o;
  }, [c]);
  useEffect(() => {
    if (!c || series) return;
    // default: the series with the largest baseline/modified divergence among tanks
    let best = options[0]?.id ?? "";
    let bestD = -1;
    for (const [tid, d] of Object.entries(c.tanks)) {
      const diff = Math.abs((d.end_level_pct?.modified ?? 0) - (d.end_level_pct?.baseline ?? 0));
      if (diff > bestD) { bestD = diff; best = `tank:${tid}:level_pct`; }
    }
    setSeries(best);
  }, [c, options, series]);

  if (cmp.error) return <ErrorState error={cmp.error} onRetry={cmp.reload} />;
  if (!c) return <Loading label="Comparing runs…" />;
  const [kind, id, qty] = series.split(":");
  const pick = (ts: Comparison["timeseries"]["baseline"]) =>
    kind === "tank" ? (ts.tanks[id] as unknown as Record<string, (number | null)[]>)?.[qty] : (ts.lines[id] as Record<string, (number | null)[]>)?.[qty];
  const n = c.timeseries.length;
  const rows = c.timeseries.timestamps.slice(0, n).map((t, i) => ({
    t, [`Baseline (${c.baseline_id})`]: pick(c.timeseries.baseline)?.[i] ?? null, [`Modified (${c.modified_id})`]: pick(c.timeseries.modified)?.[i] ?? null,
  }));
  const unit = options.find((o) => o.id === series)?.unit;
  const kpiOrder = ["total_inflow_m3", "total_outflow_m3", "demand_served_pct", "true_leak_m3", "overflow_m3", "storage_change_m3",
    "pump_energy_kwh", "specific_energy_kwh_per_m3", "measured_balance_error_pct", "mass_balance_status", "anomaly_count", "critical_anomalies"];
  return (
    <div className="space-y-4">
      {c.warnings.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{c.warnings.join(" ")}</div>}
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="overflow-x-auto">
          <table className="table">
            <thead><tr><th>KPI</th><th className="text-right">Baseline · {c.baseline_scenario}</th><th className="text-right">Modified · {c.modified_scenario}</th><th className="text-right">Δ</th><th className="text-right">Δ %</th></tr></thead>
            <tbody>
              {kpiOrder.filter((k) => c.kpis[k]).map((k) => {
                const v = c.kpis[k];
                const show = (x: number | string | null) => (typeof x === "number" ? fmt.n(x, 2) : x ?? "—");
                return (
                  <tr key={k}>
                    <td>{fmt.label(k.replace(/_m3$|_kwh$|_pct$/, ""))}{k.endsWith("_m3") ? " (m³)" : k.endsWith("_kwh") ? " (kWh)" : k.endsWith("_pct") ? " (%)" : ""}</td>
                    <td className="text-right num">{show(v.baseline)}</td>
                    <td className="text-right num">{show(v.modified)}</td>
                    <td className={`text-right num ${v.delta && v.delta !== 0 ? "font-semibold" : ""}`}>{v.delta === null ? "—" : (v.delta > 0 ? "+" : "") + fmt.n(v.delta, 2)}</td>
                    <td className="text-right num">{v.delta_pct === null ? "—" : `${v.delta_pct > 0 ? "+" : ""}${fmt.n(v.delta_pct, 1)}%`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2">
            <label className="text-xs text-ink-2" htmlFor="cmp-series">Overlay series</label>
            <select id="cmp-series" className="input py-1 text-xs" value={series} onChange={(e) => setSeries(e.target.value)}>
              {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </div>
          <ChartBox label="Baseline vs modified overlay" height={260}>
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                {Grid({})}{TimeAxis({})}{ValueAxis({ unit: unit })}{ChartTooltip({ unit: unit })}{ChartLegend({})}
                <Line dataKey={`Baseline (${c.baseline_id})`} stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey={`Modified (${c.modified_id})`} stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartBox>
        </div>
      </div>
    </div>
  );
}

function RunResult({ simId, onCompare }: { simId: string; onCompare: (a: string, b: string) => void }) {
  const run = useApi(() => api.get<SimulationDetail>(`/simulations/${simId}`), [simId]);
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  if (!run.data) return <Loading label="Loading simulation…" />;
  const r = run.data;
  const exportBtns = (
    <>
      {r.status === "COMPLETED" && (
        <>
          <button className="btn-secondary py-1 text-xs" onClick={() => download(`/simulations/${r.id}/export`, { format: "csv", content: "timeseries" })}><Download size={13} /> Time series CSV</button>
          <button className="btn-secondary py-1 text-xs" onClick={() => download(`/simulations/${r.id}/export`, { format: "csv", content: "readings" })}><Download size={13} /> Readings CSV</button>
        </>
      )}
      <button className="btn-secondary py-1 text-xs" onClick={() => download(`/simulations/${r.id}/export`, { format: "json" })}><Download size={13} /> Full JSON</button>
    </>
  );
  return (
    <div className="space-y-4">
      <Card title={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{r.id}</span><StatusPill status={r.status} /><span className="font-normal text-ink-2">{r.name}</span></span>}
        subtitle={`${fmt.label(r.scenario)} · ${r.facility_id} · ${r.steps} steps × ${r.step_minutes} min · seed ${r.seed} · ran in ${fmt.n(r.duration_ms, 0)} ms · input hash ${r.input_hash?.slice(0, 12)}`}
        actions={exportBtns}>
        {r.status === "FAILED" ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div className="mb-1 font-semibold">Input validation failed — the run was recorded but not executed.</div>
            <ul className="list-disc pl-5">{(r.validation_errors ?? []).map((e, i) => <li key={i}><span className="font-mono">{e.field}</span>: {e.message}</li>)}</ul>
          </div>
        ) : r.summary ? <Kpis run={r} /> : null}
      </Card>
      {r.status === "COMPLETED" && r.summary && r.timeseries && (
        <>
          <div className="grid gap-4 xl:grid-cols-[1fr_2fr]">
            <Card title="Anomalies by type"><AnomalyTypeChart byType={r.summary.anomalies_by_type} /></Card>
            <MassBalancePanel run={r} />
          </div>
          <RunCharts run={r} />
          <RunAnomalies simId={r.id} />
          {r.baseline_simulation_id && (
            <Card title="Baseline vs modified" subtitle={`Baseline ${r.baseline_simulation_id} uses the original configuration, same seed and horizon.`}
              actions={<button className="btn-ghost py-1 text-xs" onClick={() => onCompare(r.baseline_simulation_id!, r.id)}><GitCompare size={13} /> Open in comparison</button>}>
              <ComparePanel baselineId={r.baseline_simulation_id} modifiedId={r.id} />
            </Card>
          )}
        </>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Assumptions & limitations">
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-2">{(r.assumptions ?? []).map((a, i) => <li key={i}>{a}</li>)}</ul>
        </Card>
        <Card title="Inputs" subtitle="Captured with the run for traceability">
          {(["modified_parameters", "effective_config", "original_config"] as const).map((k) => (
            <details key={k} className="mb-2 text-xs">
              <summary className="cursor-pointer font-medium">{fmt.label(k)}</summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded bg-stone-50 p-2 font-mono text-[11px]">{JSON.stringify(r[k], null, 2)}</pre>
            </details>
          ))}
        </Card>
      </div>
    </div>
  );
}

// ------------------------------------------------------------ page
export default function SimulationStudio() {
  const { concreteId: facilityId } = useFacility();
  const { notify } = useToast();
  const [search, setSearch] = useSearchParams();
  const currentId = search.get("id") ?? "";
  const scenarios = useApi(() => api.get<{ scenarios: ScenarioInfo[] }>("/simulations/scenarios", { facility_id: facilityId }), [facilityId]);
  const modes = useApi(() => api.get<OperatingMode[]>("/operating-modes"));
  const equipment = useEquipment(facilityId);

  const [scenario, setScenario] = useState("LEAKAGE");
  const [name, setName] = useState("");
  const [seed, setSeed] = useState("20261022");
  const [steps, setSteps] = useState("96");
  const [stepMinutes, setStepMinutes] = useState(15);
  const [faultStart, setFaultStart] = useState("");
  const [runBaseline, setRunBaseline] = useState(true);
  const [applyPreset, setApplyPreset] = useState(true);
  const [params, setParams] = useState<SimulationParameters>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverErrors, setServerErrors] = useState<{ field?: string; message: string }[]>([]);
  const [running, setRunning] = useState(false);
  const [histSkip, setHistSkip] = useState(0);
  const [compareSel, setCompareSel] = useState<string[]>([]);
  const [comparePair, setComparePair] = useState<[string, string] | null>(null);

  useEffect(() => {
    setParams({});
    setErrors({});
    setServerErrors([]);
    setHistSkip(0);
    setCompareSel([]);
  }, [facilityId]);

  const history = useApi(() => api.get<Page<SimulationListItem>>("/simulations", { facility_id: facilityId, skip: histSkip, limit: HIST_LIMIT }), [facilityId, histSkip]);
  const specs = useMemo(() => (equipment.data ? overrideSpecs(equipment.data) : []), [equipment.data]);
  const scenarioInfo = scenarios.data?.scenarios.find((s) => s.id === scenario);
  const setMap = (key: MapKey, v: Record<string, number | boolean | string> | undefined) =>
    setParams((p) => ({ ...p, [key]: v } as SimulationParameters));

  const run = async () => {
    const e = validate(params, specs, { seed, steps, faultStart });
    setErrors(e);
    setServerErrors([]);
    if (Object.keys(e).length) {
      notify("error", "Fix the highlighted parameters before running.");
      return;
    }
    const clean: SimulationParameters = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || (typeof v === "object" && Object.keys(v).length === 0)) continue;
      (clean as Record<string, unknown>)[k] = v;
    }
    setRunning(true);
    try {
      const res = await api.post<SimulationDetail>("/simulations", {
        facility_id: facilityId, scenario, name, seed: Number(seed), steps: Number(steps), step_minutes: stepMinutes,
        fault_start_step: faultStart === "" ? null : Number(faultStart), parameters: clean, apply_preset: applyPreset,
        run_baseline: runBaseline,
      });
      notify("success", `${res.id} completed: ${res.summary?.kpis.anomaly_count ?? 0} anomalies, balance ${res.summary?.kpis.mass_balance_status ?? "—"}`);
      setSearch({ id: res.id });
      setHistSkip(0);
      history.reload();
    } catch (err) {
      const ae = err as ApiError;
      setServerErrors(ae.details?.length ? ae.details : [{ message: ae.message }]);
      const fe: Record<string, string> = {};
      ae.details?.forEach((d) => d.field && (fe[d.field] = d.message));
      setErrors(fe);
      let failedId = "";
      if (ae.status === 422) {
        try {
          const latest = await api.get<Page<SimulationListItem>>("/simulations", { facility_id: facilityId, status: "FAILED", limit: 1 });
          failedId = latest.items[0]?.id ?? "";
        } catch { /* ignore */ }
      }
      notify("error", `Simulation rejected${failedId ? ` (recorded as ${failedId})` : ""}: ${ae.message}`);
      history.reload();
    } finally {
      setRunning(false);
    }
  };

  const toggleCompare = (id: string) =>
    setCompareSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 2 ? [s[1], id] : [...s, id]));

  return (
    <div>
      <PageHeader title="Simulation Studio" subtitle={`Configure scenarios for ${facilityId}, execute the hydraulic model, run detection, and compare against a baseline. Every run is stored immutably.`}
        actions={<button className="btn-secondary" onClick={() => { history.reload(); scenarios.reload(); }}><RefreshCw size={14} /> Refresh</button>} />
      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        {/* ------------------------------------------------ configuration */}
        <div className="space-y-4">
          <Card title="Scenario">
            {scenarios.error ? <ErrorState error={scenarios.error} onRetry={scenarios.reload} /> : !scenarios.data ? <Loading /> : (
              <div className="space-y-3">
                <Field label="Scenario">
                  <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                    {scenarios.data.scenarios.map((s) => <option key={s.id} value={s.id}>{fmt.label(s.id)}</option>)}
                  </select>
                </Field>
                <p className="text-xs text-ink-2">{scenarioInfo?.description}</p>
                <div className="rounded-md border border-line bg-stone-50 p-2 text-xs">
                  <div className="mb-1 flex items-center justify-between font-medium">
                    Preset parameters
                    <label className="flex items-center gap-1 font-normal"><input type="checkbox" checked={applyPreset} onChange={(e) => setApplyPreset(e.target.checked)} /> apply</label>
                  </div>
                  {scenarioInfo?.preset && Object.keys(scenarioInfo.preset).length ? (
                    <ul className={`space-y-0.5 font-mono ${applyPreset ? "" : "line-through opacity-50"}`}>
                      {Object.entries(scenarioInfo.preset).map(([k, v]) => <li key={k}>{k}: {typeof v === "object" ? Object.entries(v as object).map(([a, b]) => `${a}=${b}`).join(", ") : String(v)}</li>)}
                    </ul>
                  ) : <span className="text-ink-3">None — stored configuration only.</span>}
                  <p className="mt-1 text-[11px] text-ink-3">Your overrides below take precedence over preset values.</p>
                </div>
              </div>
            )}
          </Card>
          <Card title="Run settings">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><Field label="Run name (optional)"><input className="input" value={name} maxLength={160} onChange={(e) => setName(e.target.value)} placeholder="e.g. Leak on train A" /></Field></div>
              <Field label="Seed" error={errors.seed}><input className="input num" value={seed} onChange={(e) => setSeed(e.target.value)} /></Field>
              <Field label="Steps" error={errors.steps} hint="8–672"><input className="input num" type="number" value={steps} onChange={(e) => setSteps(e.target.value)} /></Field>
              <Field label="Step length" error={errors.step_minutes}>
                <select className="input" value={stepMinutes} onChange={(e) => setStepMinutes(Number(e.target.value))}>{STEP_MINUTES.map((m) => <option key={m} value={m}>{m} min</option>)}</select>
              </Field>
              <Field label="Fault start step" error={errors.fault_start_step} hint={`Default: steps/4 = ${Math.floor(Number(steps) / 4) || 0}`}>
                <input className="input num" type="number" value={faultStart} onChange={(e) => setFaultStart(e.target.value)} placeholder="auto" />
              </Field>
              <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={runBaseline} onChange={(e) => setRunBaseline(e.target.checked)} /> Also run a baseline (original configuration) for comparison</label>
            </div>
          </Card>
          <Card title="Operating parameters" subtitle="Operational setpoints are known to the detector; fault parameters are hidden from it.">
            {equipment.error ? <ErrorState error={equipment.error} onRetry={equipment.reload} /> : !equipment.data || !modes.data ? <Loading /> : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Operating mode" error={errors.operating_mode_id}>
                    <select className="input" value={params.operating_mode_id ?? ""} onChange={(e) => setParams((p) => ({ ...p, operating_mode_id: e.target.value || undefined }))}>
                      <option value="">(none)</option>
                      {modes.data.map((m) => <option key={m.id} value={m.id}>{m.name} (×{m.demand_factor} demand)</option>)}
                    </select>
                  </Field>
                  <Field label="Demand factor" error={errors.demand_factor} hint="0–3, multiplies consumer demand">
                    <input className="input num" type="number" step={0.05} min={0} max={3} value={params.demand_factor ?? ""} placeholder="preset / 1.0"
                      onChange={(e) => setParams((p) => ({ ...p, demand_factor: e.target.value === "" ? undefined : Number(e.target.value) }))} />
                  </Field>
                </div>
                {specs.map((s) => (
                  <OverrideEditor key={s.key} spec={s} value={params[s.key] as Record<string, number | boolean | string> | undefined}
                    onChange={(v) => setMap(s.key, v)} errors={errors} />
                ))}
              </div>
            )}
          </Card>
          {serverErrors.length > 0 && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
              <div className="mb-1 font-semibold">The backend rejected the inputs:</div>
              <ul className="list-disc pl-5">{serverErrors.map((e, i) => <li key={i}>{e.field && <span className="font-mono">{e.field}: </span>}{e.message}</li>)}</ul>
            </div>
          )}
          <button className="btn-primary w-full justify-center py-2" onClick={run} disabled={running || !facilityId || !scenarios.data}>
            <Play size={15} /> {running ? "Running simulation…" : `Run ${fmt.label(scenario)} on ${facilityId}`}
          </button>
        </div>

        {/* ------------------------------------------------ results */}
        <div className="min-w-0 space-y-4">
          {comparePair && (
            <Card title={`Comparison: ${comparePair[0]} vs ${comparePair[1]}`} actions={<button className="btn-ghost py-1 text-xs" onClick={() => setComparePair(null)}>Close</button>}>
              <ComparePanel baselineId={comparePair[0]} modifiedId={comparePair[1]} />
            </Card>
          )}
          {currentId ? (
            <RunResult key={currentId} simId={currentId} onCompare={(a, b) => setComparePair([a, b])} />
          ) : (
            <Card><EmptyState title="No simulation selected" hint="Configure a scenario and press Run, or pick a run from the history below." /></Card>
          )}
          <Card title="Simulation history" subtitle="Runs are never overwritten. Tick two completed runs to compare (first = baseline)." bodyClass="p-0"
            actions={<button className="btn-secondary py-1 text-xs" disabled={compareSel.length !== 2} onClick={() => setComparePair([compareSel[0], compareSel[1]])}><GitCompare size={13} /> Compare selected</button>}>
            {history.error ? <div className="p-4"><ErrorState error={history.error} onRetry={history.reload} /></div> : !history.data ? <Loading /> :
              history.data.items.length === 0 ? <EmptyState title="No simulations yet" hint={<span className="inline-flex items-center gap-1"><FlaskConical size={12} /> Run your first scenario.</span>} /> : (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead><tr><th className="w-8"><span className="sr-only">Compare</span></th><th>ID</th><th>Created</th><th>Scenario</th><th>Status</th><th className="text-right">Steps</th><th className="text-right">Anomalies</th><th>Balance</th><th>Baseline</th></tr></thead>
                    <tbody>
                      {history.data.items.map((s) => (
                        <tr key={s.id} className={`cursor-pointer ${s.id === currentId ? "bg-brand-50" : ""}`} onClick={() => setSearch({ id: s.id })}>
                          <td onClick={(e) => e.stopPropagation()}>
                            <input type="checkbox" aria-label={`Select ${s.id} for comparison`} disabled={s.status !== "COMPLETED"} checked={compareSel.includes(s.id)} onChange={() => toggleCompare(s.id)} />
                          </td>
                          <td className="font-mono text-xs">{s.id}</td>
                          <td className="whitespace-nowrap num text-xs">{fmt.dt(s.created_at)}</td>
                          <td className="whitespace-nowrap">{fmt.label(s.scenario)}<div className="max-w-48 truncate text-xs text-ink-2">{s.name}</div></td>
                          <td><StatusPill status={s.status} /></td>
                          <td className="text-right num">{s.steps}</td>
                          <td className="text-right num">{s.summary?.kpis.anomaly_count ?? "—"}</td>
                          <td>{s.summary ? <StatusPill status={s.summary.kpis.mass_balance_status} /> : <span className="text-xs text-ink-3">{s.validation_errors?.length ?? 0} error(s)</span>}</td>
                          <td className="font-mono text-xs">{s.baseline_simulation_id ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            {history.data && <Pagination skip={histSkip} limit={HIST_LIMIT} total={history.data.total} onChange={setHistSkip} />}
          </Card>
        </div>
      </div>
    </div>
  );
}
