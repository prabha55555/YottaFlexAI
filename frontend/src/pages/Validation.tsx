import { CheckCircle2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { FormEvent, ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { NegativeScenarios, ValidationReport } from "../api/types";
import { useApi } from "../components/hooks";
import { Card, ErrorState, Loading, PageHeader, Stat, StatusPill, fmt } from "../components/ui";

function NoErrors({ text = "No errors found" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
      <CheckCircle2 size={16} /> {text}
    </div>
  );
}

function Section({ title, subtitle, count, children }: { title: string; subtitle?: string; count: number; children: ReactNode }) {
  return (
    <Card
      title={<span className="flex items-center gap-2">{title} <StatusPill status={count === 0 ? "OK" : "CRITICAL"}>{count === 0 ? "Pass" : `${count} issue${count === 1 ? "" : "s"}`}</StatusPill></span>}
      subtitle={subtitle}
    >
      {children}
    </Card>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="table">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function NegativeSection() {
  const neg = useApi(() => api.get<NegativeScenarios>("/validation/negative-scenarios"));
  return (
    <Card
      title="Required negative scenarios"
      subtitle="Deliberately invalid fixtures from backend/negative_cases/ run through the production validators. They are never loaded into the baseline database. FAILED validation = correctly rejected."
      actions={<button className="btn-secondary" onClick={neg.reload}>Re-run</button>}
    >
      {neg.error ? (
        <ErrorState error={neg.error} onRetry={neg.reload} />
      ) : !neg.data ? (
        <Loading label="Running negative scenarios…" />
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm">
            {neg.data.caught === neg.data.total ? <ShieldCheck size={18} className="text-good" /> : <ShieldAlert size={18} className="text-critical" />}
            <span className="num"><b>{neg.data.caught}</b> of <b>{neg.data.total}</b> invalid inputs rejected with the expected error.</span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {neg.data.cases.map((c) => (
              <div key={c.case_id} className="rounded-md border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-ink-2">{c.case_id}</span>
                  <span className="font-semibold">{c.title}</span>
                </div>
                <p className="mt-1 text-xs text-ink-2">{c.description}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span>Validation:</span>
                  <StatusPill status={c.validation_status === "FAILED" ? "WARNING" : "OK"}>{c.validation_status}</StatusPill>
                  <span>Expected:</span>
                  <code className="rounded bg-stone-100 px-1">{c.expected_error_code}</code>
                  {c.detected_as_expected ? (
                    <span className="flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 size={13} /> Caught</span>
                  ) : (
                    <span className="flex items-center gap-1 font-semibold text-critical"><XCircle size={13} /> Missed</span>
                  )}
                </div>
                <ul className="mt-2 space-y-1">
                  {c.errors.map((e, i) => (
                    <li key={i} className="rounded bg-red-50 px-2 py-1 text-xs text-red-900">
                      <code className="font-semibold">{e.code}</code>: {e.message}
                    </li>
                  ))}
                </ul>
                {Object.keys(c.evidence ?? {}).length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-ink-2">Evidence</summary>
                    <pre className="mt-1 max-h-56 overflow-auto rounded bg-stone-50 p-2 text-[11px]">{JSON.stringify(c.evidence, null, 2)}</pre>
                  </details>
                )}
                <div className="mt-2 text-[11px] text-ink-3">Fixture: {c.fixture}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function Validation() {
  const [tolInput, setTolInput] = useState("2");
  const [tol, setTol] = useState<number | undefined>(undefined);
  const [tolErr, setTolErr] = useState("");
  const rep = useApi(() => api.get<ValidationReport>("/validation/report", { tolerance_pct: tol }), [tol]);

  const applyTol = (e: FormEvent) => {
    e.preventDefault();
    const n = Number(tolInput);
    if (!Number.isFinite(n) || n <= 0 || n > 50) {
      setTolErr("Enter a tolerance between 0 and 50 %.");
      return;
    }
    setTolErr("");
    setTol(n);
  };

  const r = rep.data;
  const topoErrors = r ? r.topology.facilities.reduce((a, f) => a + f.errors, 0) : 0;
  const simErrors = r ? r.simulations.errors.length : 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Data Validation"
        subtitle="Integrity checks computed live from the database: keys, references, topology, tank capacity, mass balance, sensor readings and simulations."
        actions={
          <form onSubmit={applyTol} className="flex items-end gap-2">
            <label className="text-xs text-ink-2">
              Mass-balance tolerance (%)
              <input className="input w-24 num" type="number" step="0.1" min="0.1" max="50" value={tolInput} onChange={(e) => setTolInput(e.target.value)} />
            </label>
            <button className="btn-secondary" type="submit">Apply</button>
            <button className="btn-secondary" type="button" onClick={rep.reload}>Refresh</button>
            {tolErr && <span className="text-xs text-critical">{tolErr}</span>}
          </form>
        }
      />
      {rep.error ? (
        <ErrorState error={rep.error} onRetry={rep.reload} />
      ) : !r ? (
        <Loading label="Running validation checks…" />
      ) : (
        <>
          <div className={`grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7 ${rep.loading ? "opacity-60" : ""}`}>
            <Stat label="Primary key errors" value={r.primary_keys.error_count} tone={r.primary_keys.error_count ? "critical" : "good"} hint={`${fmt.n(r.primary_keys.checked_records, 0)} records checked`} />
            <Stat label="Foreign key errors" value={r.foreign_keys.error_count} tone={r.foreign_keys.error_count ? "critical" : "good"} hint={`${fmt.n(r.foreign_keys.checked_relationships, 0)} relations`} />
            <Stat label="Invalid connections" value={topoErrors} tone={topoErrors ? "critical" : "good"} hint={`${r.topology.valid_facilities}/${r.topology.total} facilities valid`} />
            <Stat label="Tank capacity violations" value={r.tank_capacity.violation_count} tone={r.tank_capacity.violation_count ? "critical" : "good"} />
            <Stat label="Mass balance failures" value={r.mass_balance.failure_count} tone={r.mass_balance.failure_count ? "warning" : "good"} hint="24 h windows" />
            <Stat label="Invalid sensor readings" value={r.sensor_readings.out_of_range_readings + r.sensor_readings.missing_readings} tone={r.sensor_readings.sensors_with_invalid_readings ? "warning" : "good"} hint={`${r.sensor_readings.sensors_with_invalid_readings} sensors affected`} />
            <Stat label="Simulation validation errors" value={simErrors} tone={simErrors ? "warning" : "good"} hint={`${r.simulations.total_runs} runs`} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Primary keys" subtitle="Duplicate IDs and identifier-format violations." count={r.primary_keys.error_count}>
              {r.primary_keys.errors.length === 0 && r.primary_keys.duplicate_telemetry_keys === 0 ? (
                <NoErrors text={`All ${fmt.n(r.primary_keys.checked_records, 0)} identifiers are unique and well-formed.`} />
              ) : (
                <Table head={["Table", "ID", "Error"]} rows={r.primary_keys.errors.map((e) => [e.table, <code>{e.id}</code>, e.message ?? e.error])} />
              )}
            </Section>
            <Section title="Foreign keys" subtitle="Equipment → facility, pipe end-points, sensor mounts, telemetry → sensor, alarm → anomaly." count={r.foreign_keys.error_count}>
              {r.foreign_keys.errors.length === 0 ? (
                <NoErrors text={`All ${fmt.n(r.foreign_keys.checked_relationships, 0)} references resolve.`} />
              ) : (
                <Table head={["Table", "ID", "Field", "Message"]} rows={r.foreign_keys.errors.map((e) => [e.table, <code>{e.id ?? "—"}</code>, e.field, e.message])} />
              )}
            </Section>
          </div>

          <Section title="Topology / invalid connections" subtitle="NetworkX validation per facility." count={topoErrors}>
            <Table
              head={["Facility", "Valid", "Errors", "Warnings", "Components", "Issues"]}
              rows={r.topology.facilities.map((f) => [
                f.facility_id,
                <StatusPill status={f.is_valid ? "OK" : "CRITICAL"}>{f.is_valid ? "Valid" : "Invalid"}</StatusPill>,
                f.errors,
                f.warnings,
                f.components,
                f.issues.length === 0 ? <span className="text-xs text-ink-3">None</span> : (
                  <ul className="space-y-0.5 text-xs">{f.issues.map((i, k) => <li key={k}><b>{i.code}</b> {i.message}</li>)}</ul>
                ),
              ])}
            />
          </Section>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Tank capacity" subtitle="Level readings outside 0–100 % imply stored volume above capacity." count={r.tank_capacity.violation_count}>
              {r.tank_capacity.violations.length === 0 ? (
                <NoErrors text="No tank reading or configuration exceeds capacity." />
              ) : (
                <Table head={["Tank", "Type", "Message"]} rows={r.tank_capacity.violations.map((v) => [v.tank_id, v.type, v.message])} />
              )}
              <div className="mt-3">
                <div className="label">Tanks at or above high-alarm level (within capacity)</div>
                {r.tank_capacity.high_level_tanks.length === 0 ? (
                  <span className="text-xs text-ink-3">None</span>
                ) : (
                  <Table head={["Tank", "Samples ≥ high alarm"]} rows={r.tank_capacity.high_level_tanks.map((t) => [t.tank_id, <span className="num">{t.samples_at_or_above_high_alarm}</span>])} />
                )}
              </div>
            </Section>
            <Section title="Mass balance" subtitle={`Facility balance per 24 h window. Mean |error| over full period: ${fmt.n(r.mass_balance.mean_abs_balance_error_pct, 3)} %.`} count={r.mass_balance.failure_count}>
              {r.mass_balance.failures.length === 0 ? (
                <NoErrors text="All windows balance within tolerance." />
              ) : (
                <Table
                  head={["Facility", "Window", "Error %", "Status", "Class", "Explanation"]}
                  rows={r.mass_balance.failures.map((f) => [
                    f.facility_id,
                    <span className="whitespace-nowrap text-xs">{fmt.dt(f.start)} – {fmt.dt(f.end)}</span>,
                    <span className="num">{fmt.n(f.balance_error_pct, 2)}</span>,
                    <StatusPill status={f.status} />,
                    <StatusPill status={f.classification} />,
                    <span className="text-xs">{f.message}</span>,
                  ])}
                />
              )}
              <div className="mt-3">
                <div className="label">Full-period facility totals</div>
                <Table
                  head={["Facility", "Inflow m³", "Residual m³", "Error %", "Status"]}
                  rows={r.mass_balance.facility_totals.map((t) => [t.facility_id, <span className="num">{fmt.n(t.total_inflow_m3, 0)}</span>, <span className="num">{fmt.n(t.residual_m3, 1)}</span>, <span className="num">{fmt.n(t.balance_error_pct, 3)}</span>, <StatusPill status={t.status} />])}
                />
              </div>
            </Section>
          </div>

          <Section title="Invalid sensor readings" subtitle="Values outside the instrument range or missing (null) in stored telemetry." count={r.sensor_readings.sensors_with_invalid_readings}>
            {r.sensor_readings.items.length === 0 ? (
              <NoErrors text="All stored readings are present and within instrument range." />
            ) : (
              <Table
                head={["Sensor", "Tag", "Facility", "Type", "Range", "Out of range", "Missing", "Min", "Max", "Readings"]}
                rows={r.sensor_readings.items.map((s) => [
                  <code>{s.sensor_id}</code>, s.tag, s.facility_id, s.sensor_type, `${s.range[0]}–${s.range[1]}`,
                  <span className="num">{s.out_of_range}</span>, <span className="num">{s.missing}</span>,
                  <span className="num">{fmt.n(s.min_value, 2)}</span>, <span className="num">{fmt.n(s.max_value, 2)}</span>, <span className="num">{s.readings}</span>,
                ])}
              />
            )}
          </Section>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Simulation validation" subtitle={`${r.simulations.completed} completed · ${r.simulations.failed} failed · success rate ${r.simulations.success_rate_pct ?? "—"} %`} count={simErrors}>
              {r.simulations.errors.length === 0 ? (
                <NoErrors text={r.simulations.total_runs ? "All simulation runs have valid, traceable inputs." : "No simulation runs recorded yet."} />
              ) : (
                <Table
                  head={["Run", "Type", "Errors"]}
                  rows={r.simulations.errors.map((s) => [
                    <Link className="font-mono text-brand-700 hover:underline" to={`/simulation?id=${s.simulation_id}`}>{s.simulation_id}</Link>,
                    s.type,
                    <ul className="space-y-0.5 text-xs">{s.errors.map((e, i) => <li key={i}><b>{e.field}</b>: {e.message}</li>)}</ul>,
                  ])}
                />
              )}
            </Section>
            <Card title="Duplicates & missing values" subtitle="Names must be unique within a facility; pipe connections and telemetry keys must be unique.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Table head={["Check", "Count"]} rows={Object.entries(r.duplicates).map(([k, v]) => [fmt.label(k), <span className="num">{v}</span>])} />
                <div className="space-y-2 text-sm">
                  <div>Telemetry rows: <b className="num">{fmt.n(r.missing_values.telemetry_rows, 0)}</b></div>
                  <div>Missing values: <b className="num">{r.missing_values.telemetry_missing_values}</b> ({fmt.n(r.missing_values.telemetry_missing_pct, 3)} %)</div>
                  {r.missing_values.missing_by_sensor.length > 0 && (
                    <div className="text-xs text-ink-2">By sensor: {r.missing_values.missing_by_sensor.map((m) => `${m.sensor_id} (${m.missing})`).join(", ")}</div>
                  )}
                  <div className="label pt-2">Required-field nulls</div>
                  <div className="text-xs">{Object.entries(r.missing_values.required_field_nulls).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>
                  <div className="text-xs text-ink-2">Alarm history: {r.alarm_history.events} events, {r.alarm_history.alarms_without_history} alarms without history.</div>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
      <NegativeSection />
    </div>
  );
}
