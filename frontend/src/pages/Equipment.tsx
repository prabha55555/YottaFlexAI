import { Pencil, Plus, RefreshCw, Search, Trash2, Workflow, X } from "lucide-react";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, XAxis } from "recharts";
import { api, ApiError } from "../api/client";
import type { Facility, Page, Pipe, Pump, SeriesResponse, Sensor, Tank, Valve } from "../api/types";
import { ChartBox, ChartTooltip, Grid, SERIES, ValueAxis, axisProps, zipSeries } from "../components/charts";
import { useApi, useFacility, useToast } from "../components/hooks";
import { Card, EmptyState, ErrorState, Field, KeyValue, Loading, Modal, PageHeader, Pagination, StatusPill, fmt } from "../components/ui";

type Kind = "pumps" | "tanks" | "valves" | "pipes" | "sensors";
type Row = Record<string, unknown> & { id: string; facility_id: string; name: string };
type FieldType = "text" | "number" | "select" | "checkbox" | "textarea" | "node" | "equipment";

interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  min?: number;
  max?: number;
  exclusiveMin?: boolean;
  exclusiveMax?: boolean;
  step?: string;
  options?: string[];
  hint?: string;
  default?: unknown;
}
interface Column { key: string; label: string; render?: (r: Row) => ReactNode; num?: boolean }
interface KindConfig {
  title: string;
  singular: string;
  subtitle: string;
  columns: Column[];
  fields: FieldDef[];
  filterLabel: string;
  filterOptions: string[];
  crossValidate?: (v: Record<string, unknown>) => Record<string, string>;
}

const STATUS_EQ = ["IN_SERVICE", "OUT_OF_SERVICE"];
const num = (d = 1) => (r: Row, k: string) => fmt.n(r[k] as number, d);

const CONFIG: Record<Kind, KindConfig> = {
  pumps: {
    title: "Pumps",
    singular: "pump",
    subtitle: "Centrifugal pumps with simplified curve H(Q) = s²·H0 − k·Q².",
    filterLabel: "Status",
    filterOptions: ["RUNNING", "STOPPED", "MAINTENANCE", "TRIPPED"],
    columns: [
      { key: "rated_flow_m3h", label: "Rated flow (m³/h)", num: true },
      { key: "shutoff_head_m", label: "H0 (m)", num: true },
      { key: "speed_pct", label: "Speed %", num: true },
      { key: "health_factor", label: "Health", num: true },
      { key: "available", label: "Available", render: (r) => (r.available ? "Yes" : "No") },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status as string} /> },
    ],
    fields: [
      { key: "name", label: "Name", type: "text", required: true },
      { key: "rated_flow_m3h", label: "Rated flow (m³/h)", type: "number", required: true, min: 0, exclusiveMin: true, max: 5000 },
      { key: "shutoff_head_m", label: "Shut-off head H0 (m)", type: "number", required: true, min: 0, exclusiveMin: true, max: 500 },
      { key: "curve_k", label: "Curve coefficient k (m/(m³/h)²)", type: "number", required: true, min: 0, exclusiveMin: true, step: "any" },
      { key: "speed_pct", label: "Speed (%)", type: "number", min: 0, max: 110, default: 100 },
      { key: "rated_power_kw", label: "Rated power (kW)", type: "number", min: 0, exclusiveMin: true, default: 30 },
      { key: "best_efficiency", label: "Best efficiency (0–1)", type: "number", min: 0, exclusiveMin: true, max: 1, step: "any", default: 0.75 },
      { key: "health_factor", label: "Health factor (0–1)", type: "number", min: 0, exclusiveMin: true, max: 1, step: "any", default: 1, hint: "1 = new; <1 = known degradation" },
      { key: "status", label: "Status", type: "select", options: ["RUNNING", "STOPPED", "MAINTENANCE", "TRIPPED"], default: "RUNNING" },
      { key: "available", label: "Available", type: "checkbox", default: true },
    ],
  },
  tanks: {
    title: "Tanks",
    singular: "tank",
    subtitle: "Storage tanks; levels integrate V(t+1) = V(t) + (Qin − Qout − Qleak)·Δt.",
    filterLabel: "Status",
    filterOptions: STATUS_EQ,
    columns: [
      { key: "capacity_m3", label: "Capacity (m³)", num: true },
      { key: "height_m", label: "Height (m)", num: true },
      { key: "elevation_m", label: "Elevation (m)", num: true },
      { key: "setpoint_pct", label: "Setpoint %", num: true },
      { key: "high_alarm_pct", label: "High alarm %", num: true },
      { key: "low_alarm_pct", label: "Low alarm %", num: true },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status as string} /> },
    ],
    fields: [
      { key: "name", label: "Name", type: "text", required: true },
      { key: "capacity_m3", label: "Capacity (m³)", type: "number", required: true, min: 0, exclusiveMin: true, max: 1_000_000 },
      { key: "height_m", label: "Height (m)", type: "number", required: true, min: 0, exclusiveMin: true, max: 100 },
      { key: "elevation_m", label: "Elevation (m)", type: "number", min: -50, max: 500, default: 0 },
      { key: "initial_level_pct", label: "Initial level (%)", type: "number", min: 0, max: 100, default: 50, hint: "Must stay within 0–100 % of capacity" },
      { key: "setpoint_pct", label: "Setpoint (%)", type: "number", min: 0, max: 100, default: 50 },
      { key: "high_alarm_pct", label: "High alarm (%)", type: "number", min: 0, exclusiveMin: true, max: 100, default: 95 },
      { key: "low_alarm_pct", label: "Low alarm (%)", type: "number", min: 0, max: 100, exclusiveMax: true, default: 10 },
      { key: "status", label: "Status", type: "select", options: STATUS_EQ, default: "IN_SERVICE" },
    ],
    crossValidate: (v): Record<string, string> => (Number(v.low_alarm_pct) >= Number(v.high_alarm_pct) ? { low_alarm_pct: "Low alarm must be below high alarm." } : {}),
  },
  valves: {
    title: "Valves",
    singular: "valve",
    subtitle: "Inline, supply (INLET) and demand (OUTLET) valves. Resistance R = R100 / opening².",
    filterLabel: "Role / type",
    filterOptions: ["INLINE", "INLET", "OUTLET", "GATE", "GLOBE", "BUTTERFLY", "BALL", "CONTROL", "CHECK"],
    columns: [
      { key: "valve_type", label: "Type" },
      { key: "role", label: "Role" },
      { key: "opening_pct", label: "Opening %", num: true },
      { key: "boundary_flow_m3h", label: "Boundary flow (m³/h)", num: true },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status as string} /> },
    ],
    fields: [
      { key: "name", label: "Name", type: "text", required: true },
      { key: "valve_type", label: "Valve type", type: "select", options: ["GATE", "GLOBE", "BUTTERFLY", "BALL", "CONTROL", "CHECK"], default: "GATE" },
      { key: "role", label: "Role", type: "select", options: ["INLINE", "INLET", "OUTLET"], default: "INLINE" },
      { key: "opening_pct", label: "Opening (%)", type: "number", min: 0, max: 100, default: 100 },
      { key: "resistance_full_open", label: "Resistance at 100 % (m/(m³/h)²)", type: "number", min: 0, exclusiveMin: true, step: "any", default: 0.0001 },
      { key: "boundary_flow_m3h", label: "Boundary flow (m³/h)", type: "number", min: 0, hint: "INLET: max supply · OUTLET: nominal demand" },
      { key: "status", label: "Status", type: "select", options: STATUS_EQ, default: "IN_SERVICE" },
    ],
  },
  pipes: {
    title: "Pipes",
    singular: "pipe",
    subtitle: "Directed pipe segments (flow from → to) between existing equipment nodes.",
    filterLabel: "Status",
    filterOptions: STATUS_EQ,
    columns: [
      { key: "from_node_id", label: "From", render: (r) => <span className="font-mono text-xs">{String(r.from_node_id)}</span> },
      { key: "to_node_id", label: "To", render: (r) => <span className="font-mono text-xs">{String(r.to_node_id)}</span> },
      { key: "length_m", label: "Length (m)", num: true },
      { key: "diameter_mm", label: "DN (mm)", num: true },
      { key: "max_flow_m3h", label: "Max flow (m³/h)", num: true },
      { key: "max_pressure_bar", label: "Rating (bar)", num: true },
      { key: "restriction_pct", label: "Restriction %", num: true },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status as string} /> },
    ],
    fields: [
      { key: "name", label: "Name", type: "text", required: true },
      { key: "from_node_id", label: "From node", type: "node", required: true },
      { key: "to_node_id", label: "To node", type: "node", required: true },
      { key: "length_m", label: "Length (m)", type: "number", required: true, min: 0, exclusiveMin: true, max: 100000 },
      { key: "diameter_mm", label: "Diameter (mm)", type: "number", required: true, min: 0, exclusiveMin: true, max: 3000 },
      { key: "friction_factor", label: "Friction factor", type: "number", min: 0, exclusiveMin: true, max: 0.2, exclusiveMax: true, step: "any", default: 0.02 },
      { key: "max_flow_m3h", label: "Max flow (m³/h)", type: "number", required: true, min: 0, exclusiveMin: true },
      { key: "max_pressure_bar", label: "Pressure rating (bar)", type: "number", min: 0, exclusiveMin: true, max: 250, default: 10 },
      { key: "restriction_pct", label: "Known restriction (%)", type: "number", min: 0, max: 100, exclusiveMax: true, default: 0 },
      { key: "status", label: "Status", type: "select", options: STATUS_EQ, default: "IN_SERVICE" },
    ],
    crossValidate: (v): Record<string, string> => (v.from_node_id && v.from_node_id === v.to_node_id ? { to_node_id: "A pipe cannot start and end at the same node." } : {}),
  },
  sensors: {
    title: "Sensors",
    singular: "sensor",
    subtitle: "Flow, pressure and level instruments mounted on equipment. Readings are simulated.",
    filterLabel: "Sensor type",
    filterOptions: ["FLOW", "PRESSURE", "LEVEL"],
    columns: [
      { key: "tag", label: "Tag", render: (r) => <span className="font-mono text-xs">{String(r.tag)}</span> },
      { key: "sensor_type", label: "Type" },
      { key: "equipment_id", label: "Mounted on", render: (r) => <span className="font-mono text-xs">{String(r.equipment_id)}</span> },
      { key: "measurement_point", label: "Point" },
      { key: "range", label: "Range", render: (r) => `${fmt.n(r.min_range as number)}–${fmt.n(r.max_range as number)} ${r.unit}` },
      { key: "accuracy_pct", label: "Accuracy %", num: true },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status as string} /> },
    ],
    fields: [
      { key: "name", label: "Name", type: "text", required: true },
      { key: "tag", label: "Tag", type: "text", required: true, hint: "Unique within the facility, e.g. FT-150" },
      { key: "equipment_id", label: "Mounted on", type: "equipment", required: true },
      { key: "sensor_type", label: "Sensor type", type: "select", options: ["FLOW", "PRESSURE", "LEVEL"], default: "FLOW" },
      { key: "measurement_point", label: "Measurement point", type: "text", required: true, default: "DISCHARGE", hint: "e.g. DISCHARGE, SUCTION, OUTLET_END, LEVEL, INLET, OUTLET" },
      { key: "unit", label: "Unit", type: "text", required: true, default: "m3/h" },
      { key: "min_range", label: "Min range", type: "number", required: true, default: 0 },
      { key: "max_range", label: "Max range", type: "number", required: true, default: 100 },
      { key: "accuracy_pct", label: "Accuracy (%)", type: "number", min: 0, exclusiveMin: true, max: 10, default: 0.5 },
      { key: "status", label: "Status", type: "select", options: ["ACTIVE", "INACTIVE", "FAULTY"], default: "ACTIVE" },
    ],
    crossValidate: (v) => {
      const e: Record<string, string> = {};
      if (Number(v.min_range) >= Number(v.max_range)) e.max_range = "Max range must be above min range.";
      const allowed: Record<string, string[]> = { FLOW: ["PUMP", "PIPE", "VALVE"], PRESSURE: ["PUMP", "PIPE", "VALVE"], LEVEL: ["TANK"] };
      if (v.equipment_type && !allowed[String(v.sensor_type)]?.includes(String(v.equipment_type)))
        e.sensor_type = `A ${v.sensor_type} sensor cannot be mounted on a ${v.equipment_type}.`;
      return e;
    },
  },
};

const UNIT_FOR: Record<string, string> = { FLOW: "m3/h", PRESSURE: "bar", LEVEL: "%" };
const NODE_KINDS: [string, string][] = [["pumps", "PUMP"], ["tanks", "TANK"], ["valves", "VALVE"]];

interface NodeOption { id: string; name: string; type: string }

function useNodeOptions(facilityId: string, includePipes: boolean) {
  return useApi(async () => {
    if (!facilityId) return [] as NodeOption[];
    const kinds: [string, string][] = [...NODE_KINDS, ...(includePipes ? [["pipes", "PIPE"] as [string, string]] : [])];
    const pages = await Promise.all(kinds.map(([k]) => api.get<Page<Row>>(`/${k}`, { facility_id: facilityId, limit: 1000 })));
    return pages.flatMap((p, i) => p.items.map((r) => ({ id: r.id, name: r.name, type: kinds[i][1] })));
  }, [facilityId, includePipes]);
}

function validateField(f: FieldDef, raw: unknown): string | undefined {
  if (f.type === "checkbox") return undefined;
  const empty = raw === "" || raw === undefined || raw === null;
  if (f.required && empty) return `${f.label} is required.`;
  if (empty) return undefined;
  if (f.type === "text" && String(raw).trim().length < 2) return `${f.label} must be at least 2 characters.`;
  if (f.type === "number") {
    const n = Number(raw);
    if (!Number.isFinite(n)) return `${f.label} must be a number.`;
    if (f.min !== undefined && (f.exclusiveMin ? n <= f.min : n < f.min)) return `Must be ${f.exclusiveMin ? ">" : "≥"} ${f.min}.`;
    if (f.max !== undefined && (f.exclusiveMax ? n >= f.max : n > f.max)) return `Must be ${f.exclusiveMax ? "<" : "≤"} ${f.max}.`;
  }
  return undefined;
}

function EquipmentForm({ kind, cfg, initial, editId, facilities, defaultFacility, onCancel, onSaved }: {
  kind: Kind; cfg: KindConfig; initial: Row | null; editId?: string; facilities: Facility[]; defaultFacility: string;
  onCancel: () => void; onSaved: (r: Row) => void;
}) {
  const { notify } = useToast();
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = { facility_id: initial?.facility_id ?? defaultFacility };
    for (const f of cfg.fields) v[f.key] = initial ? initial[f.key] ?? "" : f.default ?? (f.type === "checkbox" ? false : "");
    if (kind === "pipes") {
      v.from_node_type = initial?.from_node_type ?? "";
      v.to_node_type = initial?.to_node_type ?? "";
    }
    if (kind === "sensors") v.equipment_type = initial?.equipment_type ?? "";
    return v;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const fac = String(values.facility_id ?? "");
  const nodes = useNodeOptions(kind === "pipes" || kind === "sensors" ? fac : "", kind === "sensors");
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!fac) errs.facility_id = "Facility is required.";
    for (const f of cfg.fields) {
      const m = validateField(f, values[f.key]);
      if (m) errs[f.key] = m;
    }
    Object.assign(errs, cfg.crossValidate?.(values) ?? {});
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const body: Record<string, unknown> = {};
    for (const f of cfg.fields) {
      const raw = values[f.key];
      if (f.type === "number") body[f.key] = raw === "" || raw === null ? null : Number(raw);
      else if (f.type === "text" || f.type === "textarea") body[f.key] = String(raw).trim();
      else body[f.key] = raw;
    }
    if (kind === "pipes") {
      body.from_node_type = values.from_node_type;
      body.to_node_type = values.to_node_type;
    }
    if (kind === "sensors") body.equipment_type = values.equipment_type;
    for (const [k, v] of Object.entries(body)) if (v === null && k !== "boundary_flow_m3h") delete body[k];
    if (!editId) body.facility_id = fac;
    setBusy(true);
    try {
      const saved = editId ? await api.put<Row>(`/${kind}/${editId}`, body) : await api.post<Row>(`/${kind}`, body);
      notify("success", `${cfg.singular[0].toUpperCase()}${cfg.singular.slice(1)} ${saved.id} ${editId ? "updated" : "created"}.`);
      onSaved(saved);
    } catch (err) {
      const ae = err as ApiError;
      const fe: Record<string, string> = {};
      ae.details?.forEach((d) => {
        if (d.field) fe[d.field.split(".").pop() as string] = d.message;
      });
      if (!Object.keys(fe).length && /node|equipment/i.test(ae.message)) fe[kind === "pipes" ? "from_node_id" : "equipment_id"] = ae.message;
      setErrors(fe);
      notify("error", ae.message);
    } finally {
      setBusy(false);
    }
  }

  const nodeSelect = (key: string, typeKey: string, opts: NodeOption[]) => (
    <select
      className="input"
      value={String(values[key] ?? "")}
      onChange={(e) => {
        const o = opts.find((x) => x.id === e.target.value);
        setValues((s) => ({ ...s, [key]: e.target.value, [typeKey]: o?.type ?? "" }));
      }}
    >
      <option value="">— Select —</option>
      {["PUMP", "TANK", "VALVE", "PIPE"].map((t) => {
        const group = opts.filter((o) => o.type === t);
        return group.length ? (
          <optgroup key={t} label={t}>
            {group.map((o) => <option key={o.id} value={o.id}>{o.id} · {o.name}</option>)}
          </optgroup>
        ) : null;
      })}
    </select>
  );

  return (
    <form onSubmit={submit} noValidate>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Facility *" error={errors.facility_id} hint={editId ? "Equipment cannot be moved between facilities" : undefined}>
          <select className="input" value={fac} disabled={!!editId} onChange={(e) => setValues((s) => ({ ...s, facility_id: e.target.value, from_node_id: "", to_node_id: "", equipment_id: "" }))}>
            <option value="">— Select —</option>
            {facilities.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.name}</option>)}
          </select>
        </Field>
        {cfg.fields.map((f) => {
          const label = `${f.label}${f.required ? " *" : ""}`;
          const val = values[f.key];
          let input: ReactNode;
          if (f.type === "node") {
            input = nodes.loading ? <div className="input text-ink-3">Loading nodes…</div> : nodeSelect(f.key, f.key === "from_node_id" ? "from_node_type" : "to_node_type", nodes.data ?? []);
          } else if (f.type === "equipment") {
            input = nodes.loading ? <div className="input text-ink-3">Loading equipment…</div> : nodeSelect(f.key, "equipment_type", nodes.data ?? []);
          } else if (f.type === "select") {
            input = (
              <select
                className="input"
                value={String(val ?? "")}
                onChange={(e) => {
                  set(f.key, e.target.value);
                  if (kind === "sensors" && f.key === "sensor_type" && !editId) set("unit", UNIT_FOR[e.target.value] ?? values.unit);
                }}
              >
                {f.options!.map((o) => <option key={o} value={o}>{fmt.label(o)}</option>)}
              </select>
            );
          } else if (f.type === "checkbox") {
            input = (
              <span className="flex h-[34px] items-center gap-2 text-sm">
                <input type="checkbox" checked={Boolean(val)} onChange={(e) => set(f.key, e.target.checked)} /> {Boolean(val) ? "Yes" : "No"}
              </span>
            );
          } else {
            input = (
              <input
                className="input num"
                type={f.type === "number" ? "number" : "text"}
                step={f.step ?? (f.type === "number" ? "any" : undefined)}
                min={f.min}
                max={f.max}
                value={val === null || val === undefined ? "" : String(val)}
                onChange={(e) => set(f.key, e.target.value)}
              />
            );
          }
          return (
            <Field key={f.key} label={label} error={errors[f.key]} hint={f.hint}>
              {input}
            </Field>
          );
        })}
      </div>
      {(kind === "pipes" || kind === "sensors") && nodes.error && <p className="mt-2 text-xs text-critical">Could not load node list: {nodes.error.message}</p>}
      <div className="flex justify-end gap-2 pt-4">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Saving…" : editId ? "Save changes" : `Create ${cfg.singular}`}</button>
      </div>
    </form>
  );
}

function PumpCurve({ p }: { p: Pump }) {
  const s = p.speed_pct / 100;
  const qmax = p.rated_flow_m3h * 1.3;
  const data = Array.from({ length: 27 }, (_, i) => {
    const q = (qmax * i) / 26;
    return {
      t: q.toFixed(1),
      "Nominal (health 1.0)": Math.max(s * s * p.shutoff_head_m - p.curve_k * q * q, 0),
      [`Configured (health ${p.health_factor})`]: Math.max(p.health_factor * (s * s * p.shutoff_head_m - p.curve_k * q * q), 0),
    };
  });
  const keys = Object.keys(data[0]).filter((k) => k !== "t");
  return (
    <div>
      <div className="label">Pump curve H(Q) = hf·(s²·H0 − k·Q²) — calculated from record fields</div>
      <ChartBox height={190} label={`Calculated pump curve for ${p.id}`}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 14 }}>
            {Grid({})}
            <XAxis dataKey="t" {...axisProps} label={{ value: "Q (m³/h)", position: "insideBottom", offset: -6, fill: "#52514e", fontSize: 11 }} minTickGap={30} />
            {ValueAxis({ unit: "H (m)" })}
            {ChartTooltip({ unit: "m", timeLabel: false })}
            {keys.map((k, i) => (
              <Line key={k} dataKey={k} stroke={SERIES[i]} strokeWidth={2} dot={false} strokeDasharray={i === 0 && keys.length > 1 && p.health_factor !== 1 ? "4 3" : undefined} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </ChartBox>
      <p className="mt-1 text-xs text-ink-2">Rated flow {fmt.n(p.rated_flow_m3h)} m³/h · speed {fmt.n(p.speed_pct)} % · shut-off head at speed {fmt.n(s * s * p.shutoff_head_m * p.health_factor, 2)} m</p>
    </div>
  );
}

function SensorSpark({ s }: { s: Sensor }) {
  const q = useApi(() => api.get<SeriesResponse>("/telemetry/series", { facility_id: s.facility_id, sensor_ids: s.id, max_points: 120 }), [s.id]);
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading label="Loading readings…" />;
  const vals = q.data.series[s.id];
  if (!vals || vals.every((v) => v === null)) return <EmptyState title="No readings for this sensor" />;
  const data = zipSeries(q.data.timestamps, { [s.tag]: vals });
  return (
    <div>
      <div className="label">Recorded readings (simulated, bucket-averaged)</div>
      <ChartBox height={150} label={`Readings of ${s.tag}`}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
            {Grid({})}
            <XAxis dataKey="t" hide />
            {ValueAxis({ unit: s.unit })}
            {ChartTooltip({ unit: s.unit })}
            <Line dataKey={s.tag} stroke={SERIES[0]} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartBox>
    </div>
  );
}

function DetailsPanel({ kind, row, onClose, onEdit, onDelete }: { kind: Kind; row: Row; onClose: () => void; onEdit: () => void; onDelete: () => void }) {
  const { setFacilityId } = useFacility();
  const items: [string, ReactNode][] = Object.entries(row)
    .filter(([k]) => k !== "name")
    .map(([k, v]) => [fmt.label(k), typeof v === "boolean" ? (v ? "Yes" : "No") : typeof v === "number" ? fmt.n(v, 6) : v === null ? "—" : String(v)]);
  let extra: ReactNode = null;
  if (kind === "pumps") extra = <PumpCurve p={row as unknown as Pump} />;
  if (kind === "sensors") extra = <SensorSpark s={row as unknown as Sensor} />;
  if (kind === "tanks") {
    const t = row as unknown as Tank;
    extra = (
      <div>
        <div className="label">Volume at configured levels (capacity × level %)</div>
        <table className="table">
          <thead><tr><th>Level</th><th>%</th><th>Volume (m³)</th><th>Liquid height (m)</th></tr></thead>
          <tbody>
            {([["Low alarm", t.low_alarm_pct], ["Initial", t.initial_level_pct], ["Setpoint", t.setpoint_pct], ["High alarm", t.high_alarm_pct], ["Full", 100]] as [string, number][]).map(([l, p]) => (
              <tr key={l}><td>{l}</td><td className="num">{fmt.n(p)}</td><td className="num">{fmt.n((p / 100) * t.capacity_m3)}</td><td className="num">{fmt.n((p / 100) * t.height_m, 2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (kind === "valves") {
    const v = row as unknown as Valve;
    extra = (
      <p className="text-xs text-ink-2">
        Effective resistance at {fmt.n(v.opening_pct)} % opening: {v.opening_pct <= 0.5 ? "∞ (closed)" : (v.resistance_full_open / (v.opening_pct / 100) ** 2).toExponential(3)} m/(m³/h)²
      </p>
    );
  }
  if (kind === "pipes") {
    const p = row as unknown as Pipe;
    const area = Math.PI / 4 * (p.diameter_mm / 1000) ** 2;
    extra = <p className="text-xs text-ink-2">Velocity at max flow: {fmt.n(p.max_flow_m3h / 3600 / area, 2)} m/s · flow direction {p.from_node_id} → {p.to_node_id}</p>;
  }
  return (
    <Card
      title={<span>{row.id} · {row.name}</span>}
      actions={
        <>
          <button className="btn-ghost px-2" onClick={onEdit} aria-label="Edit"><Pencil size={14} /></button>
          <button className="btn-ghost px-2 text-critical" onClick={onDelete} aria-label="Delete"><Trash2 size={14} /></button>
          <button className="btn-ghost px-2" onClick={onClose} aria-label="Close details"><X size={14} /></button>
        </>
      }
    >
      <div className="space-y-4">
        <KeyValue items={items} />
        {extra}
        <Link to="/topology" className="btn-secondary" onClick={() => setFacilityId(row.facility_id)}><Workflow size={14} /> Show in topology</Link>
      </div>
    </Card>
  );
}

export default function Equipment() {
  const { kind: rawKind } = useParams();
  const kind = rawKind as Kind;
  const cfg = CONFIG[kind];
  const { facilityId, facilities } = useFacility();
  const { notify } = useToast();
  const [skip, setSkip] = useState(0);
  const [limit, setLimit] = useState(25);
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [modal, setModal] = useState<{ mode: "create" } | { mode: "edit"; row: Row } | null>(null);
  const [confirm, setConfirm] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    setSkip(0);
    setSelected(null);
  }, [kind, facilityId, qDebounced, filter, limit]);
  useEffect(() => setFilter(""), [kind]);

  const list = useApi(
    () => (cfg ? api.get<Page<Row>>(`/${kind}`, { facility_id: facilityId, q: qDebounced, filter, skip, limit }) : Promise.resolve({ items: [], total: 0, skip: 0, limit })),
    [kind, facilityId, qDebounced, filter, skip, limit],
  );
  const facName = useMemo(() => Object.fromEntries(facilities.map((f) => [f.id, f.name])), [facilities]);

  if (!cfg) return <Navigate to="/equipment/pumps" replace />;

  async function doDelete(r: Row) {
    setDeleting(true);
    try {
      await api.del(`/${kind}/${r.id}`);
      notify("success", `${r.id} deleted.`);
      setConfirm(null);
      if (selected?.id === r.id) setSelected(null);
      list.reload();
    } catch (e) {
      notify("error", (e as ApiError).message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={`${cfg.title}`}
        subtitle={<>{cfg.subtitle} {facilityId ? <>Scope: <b>{facilityId}</b>.</> : "Scope: all facilities."}</>}
        actions={
          <>
            <button className="btn-secondary" onClick={list.reload}><RefreshCw size={14} /> Refresh</button>
            <button className="btn-primary" onClick={() => setModal({ mode: "create" })} disabled={!facilities.length}><Plus size={14} /> New {cfg.singular}</button>
          </>
        }
      />
      <div className={`grid gap-4 ${selected ? "xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]" : ""}`}>
        <Card bodyClass="p-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
            <label className="relative min-w-[220px] flex-1">
              <span className="sr-only">Search</span>
              <Search size={14} className="absolute left-2.5 top-2.5 text-ink-3" />
              <input className="input pl-8" placeholder={`Search ${cfg.title.toLowerCase()} by ID, name${kind === "sensors" ? ", tag, equipment" : kind === "pipes" ? ", node" : ""}…`} value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              {cfg.filterLabel}
              <select className="input w-auto" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All</option>
                {cfg.filterOptions.map((o) => <option key={o} value={o}>{fmt.label(o)}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              Rows
              <select className="input w-auto" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
          {list.error ? (
            <div className="p-4"><ErrorState error={list.error} onRetry={list.reload} /></div>
          ) : list.data === undefined ? (
            <Loading />
          ) : list.data.items.length === 0 ? (
            <EmptyState title={`No ${cfg.title.toLowerCase()} found`} hint={q || filter ? "Try clearing the search or filter." : "Create one with the button above."} />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Name</th>
                      {!facilityId && <th>Facility</th>}
                      {cfg.columns.map((c) => <th key={c.key} className={c.num ? "text-right" : ""}>{c.label}</th>)}
                      <th className="text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className={list.loading ? "opacity-60" : ""}>
                    {list.data.items.map((r) => (
                      <tr key={r.id} className={`cursor-pointer ${selected?.id === r.id ? "bg-brand-50" : ""}`} onClick={() => setSelected(r)}>
                        <td className="font-mono text-xs">{r.id}</td>
                        <td className="font-medium">{r.name}</td>
                        {!facilityId && <td className="text-xs text-ink-2" title={facName[r.facility_id]}>{r.facility_id}</td>}
                        {cfg.columns.map((c) => (
                          <td key={c.key} className={c.num ? "num text-right" : ""}>{c.render ? c.render(r) : c.num ? num()(r, c.key) : String(r[c.key] ?? "—")}</td>
                        ))}
                        <td className="whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
                          <button className="btn-ghost px-1.5" onClick={() => setModal({ mode: "edit", row: r })} aria-label={`Edit ${r.id}`}><Pencil size={14} /></button>
                          <button className="btn-ghost px-1.5 text-critical" onClick={() => setConfirm(r)} aria-label={`Delete ${r.id}`}><Trash2 size={14} /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination skip={skip} limit={limit} total={list.data.total} onChange={setSkip} />
            </>
          )}
        </Card>
        {selected && (
          <DetailsPanel
            kind={kind}
            row={selected}
            onClose={() => setSelected(null)}
            onEdit={() => setModal({ mode: "edit", row: selected })}
            onDelete={() => setConfirm(selected)}
          />
        )}
      </div>

      <Modal open={modal !== null} wide title={modal?.mode === "edit" ? `Edit ${modal.row.id}` : `New ${cfg.singular}`} onClose={() => setModal(null)}>
        {modal && (
          <EquipmentForm
            key={`${kind}-${modal.mode === "edit" ? modal.row.id : "new"}`}
            kind={kind}
            cfg={cfg}
            initial={modal.mode === "edit" ? modal.row : null}
            editId={modal.mode === "edit" ? modal.row.id : undefined}
            facilities={facilities}
            defaultFacility={facilityId || facilities[0]?.id || ""}
            onCancel={() => setModal(null)}
            onSaved={(r) => {
              setModal(null);
              setSelected(r);
              list.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={confirm !== null}
        title={`Delete ${cfg.singular}`}
        onClose={() => setConfirm(null)}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
            <button className="btn-danger" disabled={deleting} onClick={() => confirm && doDelete(confirm)}>{deleting ? "Deleting…" : "Delete"}</button>
          </>
        }
      >
        <p className="text-sm">
          Delete <b>{confirm?.id} · {confirm?.name}</b>? {kind !== "sensors" && "Equipment referenced by pipes or sensors cannot be deleted; the server will list the references."}
          {kind === "sensors" && " Its telemetry history will also be removed."}
        </p>
      </Modal>
    </div>
  );
}
