import { Download, Pause, Play, RefreshCw, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { api, download } from "../api/client";
import type { Page, SeriesResponse, Snapshot, SnapshotReading, TelemetryRow } from "../api/types";
import { ChartBox, ChartLegend, ChartTooltip, Grid, SERIES, TimeAxis, ValueAxis, zipSeries } from "../components/charts";
import { useApi, useFacility } from "../components/hooks";
import { Async, Card, EmptyState, ErrorState, fmt, Loading, PageHeader, Pagination, SimulatedBadge, StatusPill } from "../components/ui";

const STEP_MS = 15 * 60 * 1000;
const TYPES = [
  { key: "FLOW", label: "Flow", unit: "m³/h" },
  { key: "PRESSURE", label: "Pressure", unit: "bar" },
  { key: "LEVEL", label: "Tank level", unit: "%" },
] as const;
type SType = (typeof TYPES)[number]["key"];

interface Range { start: string | null; end: string | null; records: number; simulated: boolean; note: string }

const toMs = (s: string) => new Date(s.endsWith("Z") ? s : s + "Z").getTime();
const toIso = (ms: number) => new Date(ms).toISOString().slice(0, 19);

function ReadingTable({ rows, unit }: { rows: SnapshotReading[]; unit: string }) {
  if (rows.length === 0) return <EmptyState title="No sensors of this type" />;
  return (
    <div className="max-h-80 overflow-y-auto">
      <table className="table">
        <thead>
          <tr><th>Tag</th><th>Location</th><th className="text-right">Value ({unit})</th><th>Quality</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const span = r.max_range - r.min_range;
            const pct = r.value == null ? 0 : Math.min(100, Math.max(0, ((r.value - r.min_range) / span) * 100));
            return (
              <tr key={r.sensor_id}>
                <td>
                  <div className="font-mono text-xs font-medium">{r.tag}</div>
                  <div className="text-[11px] text-ink-3">{r.sensor_id}</div>
                </td>
                <td className="text-xs text-ink-2">{r.equipment_id}<br />{fmt.label(r.measurement_point)}</td>
                <td className="text-right">
                  <div className="num font-medium">{r.value == null ? "—" : fmt.n(r.value, 2)}</div>
                  <div className="ml-auto mt-1 h-1 w-20 rounded bg-stone-100" title={`Range ${r.min_range}–${r.max_range} ${r.unit}`}>
                    <div className="h-1 rounded bg-brand-500" style={{ width: `${pct}%` }} />
                  </div>
                  {r.derived_value != null && <div className="text-[11px] text-ink-3 num">{fmt.n(r.derived_value, 1)} {r.derived_unit}</div>}
                </td>
                <td>
                  <StatusPill status={r.quality} />
                  {r.reason && <div className="mt-0.5 max-w-[12rem] text-[11px] text-ink-2">{r.reason}</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Monitoring() {
  const { concreteId } = useFacility();
  const range = useApi(() => api.get<Range>("/telemetry/range", { facility_id: concreteId }), [concreteId]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const startMs = range.data?.start ? toMs(range.data.start) : null;
  const endMs = range.data?.end ? toMs(range.data.end) : null;

  useEffect(() => {
    if (endMs != null) setCursor(endMs);
    setPlaying(false);
  }, [endMs, concreteId]);

  useEffect(() => {
    if (!playing || cursor == null || endMs == null) return;
    if (cursor >= endMs) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setCursor((c) => Math.min((c ?? 0) + STEP_MS, endMs)), 1000);
    return () => clearTimeout(t);
  }, [playing, cursor, endMs]);

  const at = cursor != null ? toIso(cursor) : undefined;
  const snap = useApi(
    () => (at ? api.get<Snapshot>("/telemetry/snapshot", { facility_id: concreteId, at }) : Promise.resolve(undefined as unknown as Snapshot)),
    [concreteId, at],
  );

  // ---- historical trends
  const [sType, setSType] = useState<SType>("FLOW");
  const [selected, setSelected] = useState<string[]>([]);
  const [fullRange, setFullRange] = useState(false);
  const candidates = useMemo(() => (snap.data?.readings ?? []).filter((r) => r.sensor_type === sType), [snap.data, sType]);
  useEffect(() => {
    setSelected((cur) => {
      const valid = cur.filter((s) => candidates.some((c) => c.sensor_id === s));
      return valid.length ? valid : candidates.slice(0, 2).map((c) => c.sensor_id);
    });
  }, [candidates]);
  const winStart = fullRange || cursor == null ? undefined : toIso(Math.max(cursor - 24 * 3600 * 1000, startMs ?? 0));
  const series = useApi(
    () => (selected.length && at
      ? api.get<SeriesResponse>("/telemetry/series", { facility_id: concreteId, sensor_ids: selected.join(","), start: winStart, end: fullRange ? undefined : at, max_points: 300 })
      : Promise.resolve(undefined as unknown as SeriesResponse)),
    [concreteId, selected.join(","), winStart, fullRange, fullRange ? "" : at],
  );

  // ---- raw telemetry table
  const [tblSensor, setTblSensor] = useState("");
  const [skip, setSkip] = useState(0);
  const limit = 25;
  useEffect(() => setSkip(0), [tblSensor, concreteId]);
  const tbl = useApi(
    () => api.get<Page<TelemetryRow>>("/telemetry", { facility_id: concreteId, sensor_id: tblSensor, end: at, skip, limit }),
    [concreteId, tblSensor, skip, at],
  );

  const readings = snap.data?.readings ?? [];
  const quality = { GOOD: 0, SUSPECT: 0, BAD: 0 };
  readings.forEach((r) => (quality[r.quality] += 1));
  const unitOf = TYPES.find((t) => t.key === sType)!.unit;

  return (
    <div>
      <PageHeader
        title="Live Monitoring"
        subtitle={<span className="inline-flex items-center gap-2">Simulated telemetry replay — no hardware connected <SimulatedBadge /></span>}
        actions={<button className="btn-secondary" onClick={() => { range.reload(); snap.reload(); series.reload(); tbl.reload(); }}><RefreshCw size={14} /> Refresh</button>}
      />

      {range.error ? <ErrorState error={range.error} onRetry={range.reload} /> : !range.data ? <Loading /> : !range.data.start || startMs == null || endMs == null || cursor == null ? (
        <Card><EmptyState title="No telemetry for this facility" hint="Generate data with python -m scripts.generate_data" /></Card>
      ) : (
        <div className="space-y-4">
          <Card title="Replay cursor" subtitle={`${fmt.dt(range.data.start)} → ${fmt.dt(range.data.end)} UTC · ${range.data.records.toLocaleString()} records · 15-minute steps`}>
            <div className="flex flex-wrap items-center gap-3">
              <button className="btn-primary" onClick={() => { if (cursor >= endMs) setCursor(startMs); setPlaying((p) => !p); }} aria-label={playing ? "Pause replay" : "Play replay"}>
                {playing ? <Pause size={14} /> : <Play size={14} />} {playing ? "Pause" : "Play"}
              </button>
              <button className="btn-secondary" onClick={() => { setPlaying(false); setCursor(endMs); }}>
                <SkipForward size={14} /> Latest
              </button>
              <input
                type="range"
                className="min-w-[200px] flex-1 accent-brand-600"
                min={startMs}
                max={endMs}
                step={STEP_MS}
                value={cursor}
                onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }}
                aria-label="Replay time"
              />
              <div className="font-mono text-sm num">{fmt.dt(snap.data?.timestamp ?? at)} UTC</div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="text-ink-2">Sensor health at cursor:</span>
              <StatusPill status="GOOD">{quality.GOOD} good</StatusPill>
              <StatusPill status="SUSPECT">{quality.SUSPECT} suspect</StatusPill>
              <StatusPill status="BAD">{quality.BAD} bad</StatusPill>
            </div>
          </Card>

          {snap.error ? <ErrorState error={snap.error} onRetry={snap.reload} /> : !snap.data ? <Loading /> : (
            <div className="grid gap-4 xl:grid-cols-3">
              {TYPES.map((t) => (
                <Card key={t.key} title={`${t.label} readings`} subtitle={t.unit} bodyClass="p-0">
                  <ReadingTable rows={readings.filter((r) => r.sensor_type === t.key)} unit={t.unit} />
                </Card>
              ))}
            </div>
          )}

          <Card
            title="Historical trends"
            subtitle={fullRange ? "Full recorded range" : "24 h window ending at the replay cursor"}
            actions={
              <label className="flex items-center gap-1.5 text-xs text-ink-2">
                <input type="checkbox" checked={fullRange} onChange={(e) => setFullRange(e.target.checked)} /> Full range
              </label>
            }
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-md border border-line p-0.5" role="tablist">
                {TYPES.map((t) => (
                  <button key={t.key} role="tab" aria-selected={sType === t.key}
                    className={`rounded px-2.5 py-1 text-xs font-medium ${sType === t.key ? "bg-brand-600 text-white" : "text-ink-2 hover:bg-stone-100"}`}
                    onClick={() => setSType(t.key)}>{t.label}</button>
                ))}
              </div>
              <span className="text-xs text-ink-3">Select up to 4 sensors:</span>
              {candidates.map((c) => {
                const on = selected.includes(c.sensor_id);
                const idx = selected.indexOf(c.sensor_id);
                return (
                  <button key={c.sensor_id}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${on ? "border-brand-500 bg-brand-50 text-brand-700" : "border-line text-ink-2 hover:bg-stone-50"} disabled:opacity-40`}
                    disabled={!on && selected.length >= 4}
                    onClick={() => setSelected((cur) => (on ? cur.filter((x) => x !== c.sensor_id) : [...cur, c.sensor_id]))}
                    title={c.name}>
                    {on && <span className="h-2 w-2 rounded-full" style={{ background: SERIES[idx] }} />}
                    {c.tag}
                  </button>
                );
              })}
            </div>
            {selected.length === 0 ? <EmptyState title="Select at least one sensor" /> : (
              <Async state={series} isEmpty={(s) => !s || s.timestamps.length === 0} empty={<EmptyState title="No readings in this window" />}>
                {(s) => {
                  const named: Record<string, (number | null)[]> = {};
                  selected.forEach((sid) => { if (s.series[sid]) named[s.sensors[sid]?.tag ?? sid] = s.series[sid]; });
                  return (
                    <ChartBox height={280} label={`Historical ${sType.toLowerCase()} trend`}>
                      <ResponsiveContainer>
                        <LineChart data={zipSeries(s.timestamps, named)}>
                          {Grid({})}{TimeAxis({})}{ValueAxis({ unit: unitOf })}
                          {ChartTooltip({ unit: unitOf })}
                          {Object.keys(named).length >= 2 && ChartLegend({})}
                          {Object.keys(named).map((k, i) => (
                            <Line key={k} dataKey={k} stroke={SERIES[i]} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </ChartBox>
                  );
                }}
              </Async>
            )}
          </Card>

          <Card
            title="Telemetry records"
            subtitle="Raw historian rows up to the replay cursor (NULL value = missing reading)"
            bodyClass="p-0"
            actions={
              <>
                <select className="input w-auto py-1 text-xs" value={tblSensor} onChange={(e) => setTblSensor(e.target.value)} aria-label="Filter by sensor">
                  <option value="">All sensors</option>
                  {readings.map((r) => <option key={r.sensor_id} value={r.sensor_id}>{r.tag} ({r.sensor_id})</option>)}
                </select>
                <button className="btn-secondary text-xs" onClick={() => download("/telemetry/export", { facility_id: concreteId, sensor_id: tblSensor, format: "csv" })}>
                  <Download size={13} /> CSV
                </button>
                <button className="btn-secondary text-xs" onClick={() => download("/telemetry/export", { facility_id: concreteId, sensor_id: tblSensor, format: "json" })}>
                  <Download size={13} /> JSON
                </button>
              </>
            }
          >
            <Async state={tbl} isEmpty={(p) => p.items.length === 0} empty={<EmptyState title="No records" />}>
              {(p) => (
                <>
                  <div className="overflow-x-auto">
                    <table className="table">
                      <thead><tr><th>ID</th><th>Sensor</th><th>Timestamp (UTC)</th><th className="text-right">Value</th><th className="text-right">Derived</th><th>Source</th></tr></thead>
                      <tbody>
                        {p.items.map((r) => (
                          <tr key={r.id}>
                            <td className="num text-ink-2">{r.id}</td>
                            <td className="font-mono text-xs">{r.sensor_id}</td>
                            <td className="num">{fmt.dt(r.timestamp)}</td>
                            <td className="text-right num">{r.value == null ? <span className="text-critical">missing</span> : fmt.n(r.value, 3)}</td>
                            <td className="text-right num text-ink-2">{r.derived_value == null ? "—" : `${fmt.n(r.derived_value, 2)} ${r.derived_unit ?? ""}`}</td>
                            <td className="text-xs text-ink-2">{r.source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination skip={p.skip} limit={p.limit} total={p.total} onChange={setSkip} />
                </>
              )}
            </Async>
          </Card>
        </div>
      )}
    </div>
  );
}
