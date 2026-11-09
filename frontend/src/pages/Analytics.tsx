import { RefreshCw } from "lucide-react";
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { Analytics as AnalyticsT, DataQuality, Evaluation } from "../api/types";
import { axisProps, ChartBox, ChartLegend, ChartTooltip, Grid, SERIES, SEVERITY_COLOR, STATUS, ValueAxis } from "../components/charts";
import { useApi, useFacility } from "../components/hooks";
import { Async, Card, EmptyState, fmt, PageHeader, SeverityBadge, SimulatedBadge, Stat, StatusPill } from "../components/ui";

const SEVS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;

function pctOrDash(v: number | null | undefined) {
  return v == null ? "—" : fmt.pct(v, 1);
}

function SevStack({ data, xKey, label }: { data: Record<string, unknown>[]; xKey: string; label: string }) {
  return (
    <ChartBox height={240} label={label}>
      <ResponsiveContainer>
        <BarChart data={data} barCategoryGap="25%">
          {Grid({})}
          <XAxis dataKey={xKey} {...axisProps} interval={0} tick={{ fill: "#52514e", fontSize: 10 }} />
          {ValueAxis({})}
          {ChartTooltip({ timeLabel: false })}
          {ChartLegend({})}
          {SEVS.map((s, i) => (
            <Bar key={s} dataKey={s} name={fmt.label(s)} stackId="s" fill={SEVERITY_COLOR[s]} stroke="#fff" strokeWidth={1}
              radius={i === SEVS.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function DataQualityTiles({ dq }: { dq: DataQuality }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Primary key integrity" value={`${fmt.n(dq.primary_key_integrity_pct, 2)}%`} hint={`${dq.primary_key_errors} errors`} tone={dq.primary_key_errors ? "critical" : "good"} />
      <Stat label="Foreign key integrity" value={`${fmt.n(dq.foreign_key_integrity_pct, 2)}%`} hint={`${dq.foreign_key_errors} errors`} tone={dq.foreign_key_errors ? "critical" : "good"} />
      <Stat label="Duplicates" value={dq.duplicate_count} hint={`${dq.duplicates.telemetry_duplicate_readings ?? 0} telemetry · ${dq.duplicates.pipe_duplicate_connections ?? 0} pipe connections`} tone={dq.duplicates.telemetry_duplicate_readings || dq.duplicates.pipe_duplicate_connections ? "critical" : "default"} />
      <Stat label="Missing telemetry values" value={`${fmt.n(dq.missing_value_pct, 3)}%`} hint={`${dq.missing_values} readings`} tone={dq.missing_value_pct > 1 ? "warning" : "good"} />
      <Stat label="Topology validity" value={`${dq.topology_valid_facilities}/${dq.topology_total_facilities}`} hint="facilities valid" tone={dq.topology_valid_facilities === dq.topology_total_facilities ? "good" : "critical"} />
      <Stat label="Simulation success rate" value={dq.simulation_success_rate_pct == null ? "—" : `${fmt.n(dq.simulation_success_rate_pct, 1)}%`} hint={`${dq.simulation_runs} runs`} />
      <Stat label="Mass balance mean |error|" value={dq.mass_balance_mean_abs_error_pct == null ? "—" : `${fmt.n(dq.mass_balance_mean_abs_error_pct, 2)}%`} hint="Facility totals, measured" tone={(dq.mass_balance_mean_abs_error_pct ?? 0) > 2 ? "warning" : "good"} />
      <Stat label="Dataset" value={dq.dataset ? dq.dataset.scale : "—"} hint={dq.dataset ? `seed ${dq.dataset.seed} · ${dq.dataset.fingerprint.slice(0, 12)}…` : "none loaded"} />
    </div>
  );
}

function EvaluationSection({ ev }: { ev: Evaluation }) {
  if (!ev.available) return <EmptyState title="Evaluation unavailable" hint={ev.message} />;
  const types = Object.keys(ev.per_type);
  const missed = types.flatMap((t) => ev.event_level[t].details.filter((d) => !d.detected).map((d) => ({ type: t, ...d })));
  const o = ev.overall;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Precision (overall)" value={pctOrDash(o.precision)} hint={`TP ${o.tp} · FP ${o.fp}`} />
        <Stat label="Recall (overall)" value={pctOrDash(o.recall)} hint={`TP ${o.tp} · FN ${o.fn}`} />
        <Stat label="F1-score (overall)" value={pctOrDash(o.f1_score)} />
        <Stat label="Accuracy" value={pctOrDash(o.accuracy)} hint={`TN ${o.tn.toLocaleString()} of ${(o.tp + o.fp + o.tn + o.fn).toLocaleString()} units`} />
      </div>
      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Issue type</th><th className="text-right">TP</th><th className="text-right">FP</th><th className="text-right">TN</th><th className="text-right">FN</th>
              <th className="text-right">Precision</th><th className="text-right">Recall</th><th className="text-right">F1</th>
              <th className="text-right">Events detected</th><th className="text-right">Mean latency</th><th className="text-right">Severity agreement</th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => {
              const m = ev.per_type[t];
              const el = ev.event_level[t];
              return (
                <tr key={t}>
                  <td className="font-medium">{fmt.label(t)}</td>
                  <td className="text-right num">{m.tp}</td>
                  <td className="text-right num">{m.fp}</td>
                  <td className="text-right num">{m.tn.toLocaleString()}</td>
                  <td className="text-right num">{m.fn}</td>
                  <td className="text-right num">{pctOrDash(m.precision)}</td>
                  <td className="text-right num">{pctOrDash(m.recall)}</td>
                  <td className="text-right num">{pctOrDash(m.f1_score)}</td>
                  <td className="text-right num">{el.detected}/{el.labels}</td>
                  <td className="text-right num">{el.mean_latency_min == null ? "—" : `${fmt.n(el.mean_latency_min, 0)} min`}</td>
                  <td className="text-right num">{pctOrDash(el.severity_agreement)}</td>
                </tr>
              );
            })}
            <tr className="bg-stone-50 font-semibold">
              <td>Overall</td>
              <td className="text-right num">{o.tp}</td><td className="text-right num">{o.fp}</td>
              <td className="text-right num">{o.tn.toLocaleString()}</td><td className="text-right num">{o.fn}</td>
              <td className="text-right num">{pctOrDash(o.precision)}</td><td className="text-right num">{pctOrDash(o.recall)}</td>
              <td className="text-right num">{pctOrDash(o.f1_score)}</td><td colSpan={3} />
            </tr>
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-semibold">Missed ground-truth labels ({missed.length})</h3>
        <p className="mb-2 text-xs text-ink-2">
          The full dataset deliberately includes detection-limit tests (magnitudes at or below the documented thresholds,
          e.g. a 3.5 % leak against a 5 % imbalance threshold). These are expected misses and are reported, not hidden.
        </p>
        {missed.length === 0 ? <EmptyState title="No missed labels" /> : (
          <table className="table">
            <thead><tr><th>Scenario</th><th>Type</th><th>Sub-type</th><th>Equipment</th><th>Expected severity</th></tr></thead>
            <tbody>
              {missed.map((m) => (
                <tr key={m.scenario_id}>
                  <td className="font-mono text-xs">{m.scenario_id}</td>
                  <td>{fmt.label(m.type)}</td>
                  <td className="text-ink-2">{m.sub_type}</td>
                  <td className="font-mono text-xs">{m.equipment_id}</td>
                  <td><SeverityBadge severity={m.expected_severity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {ev.sensor_faults_labelled_as_process.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {ev.sensor_faults_labelled_as_process.length} sensor fault(s) were labelled as process leaks:{" "}
          {ev.sensor_faults_labelled_as_process.map((m) => `${m.scenario_id} (${m.sensor_id} → ${m.anomaly_id})`).join(", ")}
        </div>
      )}
      <p className="text-xs text-ink-2">
        <span className="font-semibold">Method:</span> {ev.method} Dataset scale {ev.scale}, seed {ev.seed}, {ev.windows} windows of {ev.window_hours} h.
      </p>
    </div>
  );
}

export default function Analytics() {
  const { concreteId } = useFacility();
  const ov = useApi(() => api.get<AnalyticsT>("/analytics/overview", { facility_id: concreteId }), [concreteId]);
  const ev = useApi(() => api.get<Evaluation>("/evaluation/metrics"), []);
  const dq = useApi(() => api.get<DataQuality>("/evaluation/data-quality"), []);
  const reload = () => { ov.reload(); ev.reload(); dq.reload(); };

  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle={<span className="inline-flex flex-wrap items-center gap-2">{concreteId} · computed from stored telemetry, anomalies, alarms and simulation runs <SimulatedBadge /></span>}
        actions={<button className="btn-secondary" onClick={reload} disabled={ov.loading}><RefreshCw size={14} className={ov.loading ? "animate-spin" : ""} /> Refresh</button>}
      />
      <div className="space-y-4">
        <Async state={ov}>
          {(a) => (
            <div className="space-y-4">
              <p className="text-xs text-ink-2">Period {fmt.dt(a.period.start)} → {fmt.dt(a.period.end)} UTC</p>
              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Equipment health — pump performance" subtitle="Performance index = measured head ÷ pump-curve head at measured flow (5th percentile); dashed line = 0.90 degradation threshold">
                  <ChartBox height={220} label="Pump performance index, 5th percentile">
                    <ResponsiveContainer>
                      <BarChart data={a.equipment_health} barCategoryGap="30%">
                        {Grid({})}
                        <XAxis dataKey="pump_id" {...axisProps} tick={{ fill: "#52514e", fontSize: 10 }} />
                        <YAxis {...axisProps} width={40} domain={[0.5, 1.05]} tickFormatter={(v: number) => v.toFixed(2)} />
                        {ChartTooltip({ timeLabel: false })}
                        <ReferenceLine y={0.9} stroke={STATUS.critical} strokeDasharray="4 3" />
                        <Bar dataKey="performance_index_p5" name="Performance index (p5)" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                          {a.equipment_health.map((p) => (
                            <Cell key={p.pump_id} fill={p.health === "CRITICAL" ? STATUS.critical : p.health === "WARNING" ? STATUS.warning : SERIES[0]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartBox>
                  <table className="table mt-2">
                    <thead><tr><th>Pump</th><th className="text-right">Mean flow</th><th className="text-right">Utilisation</th><th className="text-right">Index (median)</th><th className="text-right">Index (p5)</th><th>Health</th></tr></thead>
                    <tbody>
                      {a.equipment_health.map((p) => (
                        <tr key={p.pump_id}>
                          <td><span className="font-mono text-xs">{p.pump_id}</span> <span className="text-xs text-ink-2">{p.name}</span></td>
                          <td className="text-right num">{fmt.n(p.mean_flow_m3h, 1)} m³/h</td>
                          <td className="text-right num">{p.utilisation_pct == null ? "—" : `${fmt.n(p.utilisation_pct, 1)}%`}</td>
                          <td className="text-right num">{fmt.n(p.performance_index, 3)}</td>
                          <td className="text-right num">{fmt.n(p.performance_index_p5, 3)}</td>
                          <td><StatusPill status={p.health} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>

                <Card title="Flow analysis" subtitle="Mean pump-discharge (upstream) vs pipe-end (downstream) flow per line">
                  <ChartBox height={220} label="Upstream and downstream mean flow per line">
                    <ResponsiveContainer>
                      <BarChart data={a.flow_analysis} barGap={2} barCategoryGap="25%">
                        {Grid({})}
                        <XAxis dataKey="pump_id" {...axisProps} tick={{ fill: "#52514e", fontSize: 10 }} />
                        {ValueAxis({ unit: "m³/h" })}
                        {ChartTooltip({ unit: "m³/h", timeLabel: false })}
                        {ChartLegend({})}
                        <Bar dataKey="mean_upstream_m3h" name="Upstream" fill={SERIES[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                        <Bar dataKey="mean_downstream_m3h" name="Downstream" fill={SERIES[1]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartBox>
                  <table className="table mt-2">
                    <thead><tr><th>Line</th><th>Pipe</th><th className="text-right">Max flow</th><th className="text-right">Capacity</th><th className="text-right">Line loss</th></tr></thead>
                    <tbody>
                      {a.flow_analysis.map((f) => (
                        <tr key={f.pump_id}>
                          <td className="font-mono text-xs">{f.pump_id}</td>
                          <td className="font-mono text-xs">{f.pipe_id}</td>
                          <td className="text-right num">{fmt.n(f.max_upstream_m3h, 1)} m³/h</td>
                          <td className="text-right num">{fmt.n(f.pipe_capacity_m3h, 0)} m³/h</td>
                          <td className={`text-right num ${(f.line_loss_pct ?? 0) > 5 ? "font-semibold text-critical" : ""}`}>{f.line_loss_pct == null ? "—" : `${fmt.n(f.line_loss_pct, 2)}%`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Pressure analysis" subtitle="Pump discharge pressure against the discharge pipe rating" bodyClass="p-0">
                  <table className="table">
                    <thead><tr><th>Pump</th><th className="text-right">Suction mean</th><th className="text-right">Discharge min / mean / max</th><th className="text-right">Rating</th><th className="text-right">Max % of rating</th></tr></thead>
                    <tbody>
                      {a.pressure_analysis.map((p) => (
                        <tr key={p.pump_id}>
                          <td className="font-mono text-xs">{p.pump_id}</td>
                          <td className="text-right num">{fmt.n(p.mean_suction_bar, 2)} bar</td>
                          <td className="text-right num">{fmt.n(p.min_discharge_bar, 2)} / {fmt.n(p.mean_discharge_bar, 2)} / {fmt.n(p.max_discharge_bar, 2)} bar</td>
                          <td className="text-right num">{fmt.n(p.pipe_rating_bar, 1)} bar</td>
                          <td className="text-right">
                            <div className="flex items-center justify-end gap-2">
                              <div className="h-1.5 w-16 rounded bg-stone-100"><div className="h-1.5 rounded" style={{ width: `${Math.min(p.max_pct_of_rating ?? 0, 100)}%`, background: (p.max_pct_of_rating ?? 0) >= 90 ? STATUS.critical : SERIES[0] }} /></div>
                              <span className="num">{p.max_pct_of_rating == null ? "—" : `${fmt.n(p.max_pct_of_rating, 1)}%`}</span>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>

                <Card title="Tank utilisation" subtitle="Level range over the period (bar = min→max, tick = mean)" bodyClass="p-0">
                  <table className="table">
                    <thead><tr><th>Tank</th><th>Level range</th><th className="text-right">Mean</th><th className="text-right">≥ high alarm</th><th className="text-right">≤ low alarm</th></tr></thead>
                    <tbody>
                      {a.tank_utilisation.map((t) => (
                        <tr key={t.tank_id}>
                          <td><span className="font-mono text-xs">{t.tank_id}</span><div className="text-[11px] text-ink-2">{t.name} · {fmt.n(t.capacity_m3, 0)} m³</div></td>
                          <td className="w-40">
                            <div className="relative h-2.5 w-36 rounded bg-stone-100" title={`${fmt.n(t.min_level_pct, 1)}% – ${fmt.n(t.max_level_pct, 1)}%`}>
                              <div className="absolute h-2.5 rounded" style={{ left: `${t.min_level_pct ?? 0}%`, width: `${Math.max((t.max_level_pct ?? 0) - (t.min_level_pct ?? 0), 1)}%`, background: (t.max_level_pct ?? 0) >= 95 ? STATUS.serious : SERIES[0] }} />
                              <div className="absolute -top-0.5 h-3.5 w-0.5 bg-ink" style={{ left: `${t.mean_level_pct ?? 0}%` }} />
                            </div>
                            <div className="mt-0.5 text-[11px] text-ink-2 num">{fmt.n(t.min_level_pct, 1)}–{fmt.n(t.max_level_pct, 1)}%</div>
                          </td>
                          <td className="text-right num">{fmt.n(t.mean_level_pct, 1)}%</td>
                          <td className={`text-right num ${(t.time_above_high_pct ?? 0) > 0 ? "font-semibold text-critical" : ""}`}>{fmt.n(t.time_above_high_pct, 2)}%</td>
                          <td className={`text-right num ${(t.time_below_low_pct ?? 0) > 0 ? "font-semibold text-serious" : ""}`}>{fmt.n(t.time_below_low_pct, 2)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Anomaly distribution" subtitle="By type and severity (telemetry scan + simulations)">
                  {a.anomaly_distribution.length === 0 ? <EmptyState title="No anomalies recorded" /> : (
                    <SevStack data={a.anomaly_distribution.map((d) => ({ ...d, label: fmt.label(d.anomaly_type) }))} xKey="label" label="Anomaly count by type, stacked by severity" />
                  )}
                </Card>
                <Card title="Alarm trend" subtitle="Live alarms raised per 12-hour bucket, by severity">
                  {a.alarm_trend.length === 0 ? <EmptyState title="No live alarms" /> : (
                    <SevStack data={a.alarm_trend.map((b) => ({ ...b, label: fmt.time(b.bucket) }))} xKey="label" label="Alarms raised per 12 h bucket" />
                  )}
                </Card>
              </div>

              <Card title="Simulation performance" subtitle="Per scenario, this facility" bodyClass="p-0">
                {a.simulation_performance.length === 0 ? <EmptyState title="No simulation runs yet" hint="Run scenarios in the Simulation Studio." /> : (
                  <table className="table">
                    <thead><tr><th>Scenario</th><th className="text-right">Runs</th><th className="text-right">Completed</th><th className="text-right">Failed</th><th className="text-right">Success rate</th><th className="text-right">Mean duration</th><th className="text-right">Mean anomalies</th><th className="text-right">Mean energy</th><th className="text-right">Demand served</th></tr></thead>
                    <tbody>
                      {a.simulation_performance.map((s) => (
                        <tr key={s.scenario}>
                          <td className="font-medium">{fmt.label(s.scenario)}</td>
                          <td className="text-right num">{s.runs}</td>
                          <td className="text-right num">{s.completed}</td>
                          <td className="text-right num">{s.failed}</td>
                          <td className="text-right num">{fmt.n(s.success_rate_pct, 1)}%</td>
                          <td className="text-right num">{s.mean_duration_ms == null ? "—" : `${fmt.n(s.mean_duration_ms, 0)} ms`}</td>
                          <td className="text-right num">{fmt.n(s.mean_anomalies, 1)}</td>
                          <td className="text-right num">{s.mean_energy_kwh == null ? "—" : `${fmt.n(s.mean_energy_kwh, 0)} kWh`}</td>
                          <td className="text-right num">{s.mean_demand_served_pct == null ? "—" : `${fmt.n(s.mean_demand_served_pct, 1)}%`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            </div>
          )}
        </Async>

        <Card title="Detection evaluation" subtitle="Rule-based detections (telemetry scan) vs separate ground-truth labels — all facilities">
          <Async state={ev}>{(e) => <EvaluationSection ev={e} />}</Async>
        </Card>

        <Card title="Data quality metrics" subtitle="Computed live from the database">
          <Async state={dq}>{(d) => <DataQualityTiles dq={d} />}</Async>
        </Card>
      </div>
    </div>
  );
}
