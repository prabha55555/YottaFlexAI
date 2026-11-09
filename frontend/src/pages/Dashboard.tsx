import { Activity, AlertOctagon, Bell, Boxes, Building2, Database, FlaskConical, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { DashboardSummary } from "../api/types";
import { axisProps, ChartBox, ChartLegend, ChartTooltip, Grid, SERIES, STATUS, TimeAxis, ValueAxis, zipSeries } from "../components/charts";
import { useApi, useFacility } from "../components/hooks";
import { Async, Card, EmptyState, fmt, PageHeader, SimulatedBadge, Stat, StatusPill } from "../components/ui";

const HEALTH_KEYS = ["NORMAL", "WARNING", "CRITICAL"] as const;
const HEALTH_COLOR = { NORMAL: STATUS.good, WARNING: STATUS.warning, CRITICAL: STATUS.critical };

export default function Dashboard() {
  const { facilityId, setFacilityId, facilities } = useFacility();
  const state = useApi(() => api.get<DashboardSummary>("/dashboard/summary", { facility_id: facilityId }), [facilityId]);
  const facName = (id: string | null) => facilities.find((f) => f.id === id)?.name ?? id ?? "";

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-2">
            {facilityId ? `${facilityId} · ${facName(facilityId)}` : "All facilities"}
            {state.data?.latest_timestamp && <span>· Latest data {fmt.dt(state.data.latest_timestamp)} UTC</span>}
            <SimulatedBadge />
          </span>
        }
        actions={
          <button className="btn-secondary" onClick={state.reload} disabled={state.loading}>
            <RefreshCw size={14} className={state.loading ? "animate-spin" : ""} /> Refresh
          </button>
        }
      />
      <Async state={state}>
        {(d) => (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="Facilities" value={d.totals.facilities} icon={<Building2 size={14} />} />
              <Stat label="Equipment" value={fmt.n(d.totals.equipment, 0)} icon={<Boxes size={14} />}
                hint={`${d.totals.pumps} pumps · ${d.totals.tanks} tanks · ${d.totals.valves} valves`} />
              <Stat label="Active alarms" value={d.totals.active_alarms} icon={<Bell size={14} />}
                tone={d.totals.active_alarms ? "warning" : "good"} hint="Live (non-simulation), open" />
              <Stat label="Critical alarms" value={d.totals.critical_alarms} icon={<AlertOctagon size={14} />}
                tone={d.totals.critical_alarms ? "critical" : "good"} />
              <Stat label="Critical anomalies" value={d.totals.critical_anomalies} icon={<Activity size={14} />}
                tone={d.totals.critical_anomalies ? "critical" : "good"} hint="Telemetry scan" />
              <Stat label="Telemetry records" value={fmt.n(d.totals.telemetry_records, 0)} icon={<Database size={14} />}
                hint={`${d.totals.sensors} sensors`} />
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              <Card title="Plant operating status" subtitle="Condition derived from open live alarms" className="xl:col-span-2" bodyClass="p-0">
                <table className="table">
                  <thead>
                    <tr><th>Facility</th><th>Status</th><th>Mode</th><th>Condition</th><th className="text-right">Open alarms</th><th className="text-right">Critical</th></tr>
                  </thead>
                  <tbody>
                    {d.plant_status.map((p) => (
                      <tr key={p.facility_id} className="cursor-pointer" onClick={() => setFacilityId(p.facility_id)} title="Scope dashboard to this facility">
                        <td><div className="font-medium">{p.name}</div><div className="text-xs text-ink-2">{p.facility_id}</div></td>
                        <td><StatusPill status={p.status} /></td>
                        <td className="text-ink-2">{p.operating_mode ?? "—"}</td>
                        <td><StatusPill status={p.condition} /></td>
                        <td className="text-right num">{p.open_alarms}</td>
                        <td className="text-right num">{p.critical_alarms}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Card title="Equipment health" subtitle="Count by worst open alarm severity">
                <ChartBox height={200} label="Equipment health by class">
                  <ResponsiveContainer>
                    <BarChart layout="vertical" data={Object.entries(d.equipment_health).map(([k, v]) => ({ k: fmt.label(k), ...v }))} margin={{ left: 4, right: 12 }} barCategoryGap={6}>
                      {Grid({})}
                      <XAxis type="number" {...axisProps} allowDecimals={false} />
                      <YAxis type="category" dataKey="k" {...axisProps} width={64} />
                      {ChartTooltip({ timeLabel: false })}
                      {ChartLegend({})}
                      {HEALTH_KEYS.map((h, i) => (
                        <Bar key={h} dataKey={h} name={fmt.label(h)} stackId="a" fill={HEALTH_COLOR[h]} stroke="#fff" strokeWidth={1}
                          radius={i === HEALTH_KEYS.length - 1 ? [0, 4, 4, 0] : 0} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </ChartBox>
              </Card>
            </div>

            {d.trends && d.trends.timestamps.length > 0 ? (
              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Flow trend" subtitle={`${d.trend_facility_id} · total supply inflow vs consumer outflow (hourly mean)`}>
                  <ChartBox label="Facility inflow and outflow over time">
                    <ResponsiveContainer>
                      <LineChart data={zipSeries(d.trends.timestamps, { Inflow: d.trends.inflow, Outflow: d.trends.outflow })}>
                        {Grid({})}{TimeAxis({})}{ValueAxis({ unit: "m³/h" })}
                        {ChartTooltip({ unit: "m³/h" })}{ChartLegend({})}
                        <Line dataKey="Inflow" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Line dataKey="Outflow" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartBox>
                </Card>
                <Card title="Pressure trend" subtitle={`${d.trend_facility_id} · mean pump discharge and suction pressure`}>
                  <ChartBox label="Mean pump discharge and suction pressure over time">
                    <ResponsiveContainer>
                      <LineChart data={zipSeries(d.trends.timestamps, { Discharge: d.trends.discharge_pressure, Suction: d.trends.suction_pressure })}>
                        {Grid({})}{TimeAxis({})}{ValueAxis({ unit: "bar" })}
                        {ChartTooltip({ unit: "bar" })}{ChartLegend({})}
                        <Line dataKey="Discharge" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Line dataKey="Suction" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartBox>
                </Card>
              </div>
            ) : (
              <Card title="Trends"><EmptyState title="No telemetry yet" hint="Run python -m scripts.generate_data" /></Card>
            )}

            <div className="grid gap-4 xl:grid-cols-3">
              <Card title="Tank levels" subtitle={`At ${fmt.dt(d.latest_timestamp)} UTC · dashed line = high alarm`} className="xl:col-span-2">
                {d.tank_levels.length === 0 ? <EmptyState title="No tanks" /> : (
                  <ChartBox height={Math.max(160, d.tank_levels.length * 22 + 40)} label="Current tank levels">
                    <ResponsiveContainer>
                      <BarChart layout="vertical" data={d.tank_levels.map((t) => ({ k: t.tank_id, level: t.level_pct, name: t.name, high: t.high_alarm_pct, low: t.low_alarm_pct }))} margin={{ left: 4, right: 36 }} barCategoryGap={3}>
                        {Grid({})}
                        <XAxis type="number" domain={[0, 100]} {...axisProps} unit="%" />
                        <YAxis type="category" dataKey="k" {...axisProps} width={76} />
                        {ChartTooltip({ unit: "%", timeLabel: false })}
                        <ReferenceLine x={95} stroke={STATUS.critical} strokeDasharray="4 3" />
                        <Bar dataKey="level" name="Level" radius={[0, 4, 4, 0]} isAnimationActive={false}
                          label={{ position: "right", fontSize: 11, fill: "#52514e", formatter: (v: number) => (v == null ? "—" : `${v.toFixed(1)}%`) }}>
                          {d.tank_levels.map((t) => (
                            <Cell key={t.tank_id} fill={t.level_pct != null && t.level_pct >= t.high_alarm_pct ? STATUS.critical
                              : t.level_pct != null && t.level_pct <= t.low_alarm_pct ? STATUS.warning : SERIES[0]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartBox>
                )}
              </Card>
              <Card title="Recent simulations" actions={<Link to="/simulation" className="btn-ghost text-xs"><FlaskConical size={13} /> Studio</Link>} bodyClass="p-0">
                {d.recent_simulations.length === 0 ? <EmptyState title="No simulations yet" hint="Run one in the Simulation Studio." /> : (
                  <ul className="divide-y divide-stone-100">
                    {d.recent_simulations.map((s) => (
                      <li key={s.id}>
                        <Link to={`/simulation?id=${s.id}`} className="flex items-center gap-2 px-4 py-2.5 hover:bg-brand-50/40">
                          <div className="min-w-0 flex-1">
                            <div className="font-mono text-xs text-brand-700">{s.id}</div>
                            <div className="text-sm">{fmt.label(s.scenario)} <span className="text-ink-2">· {s.facility_id}</span></div>
                            <div className="text-xs text-ink-2">{fmt.dt(s.created_at)} · {s.anomalies ?? 0} anomalies</div>
                          </div>
                          <StatusPill status={s.status} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>
        )}
      </Async>
    </div>
  );
}
