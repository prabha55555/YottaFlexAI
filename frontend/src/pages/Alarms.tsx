import { CheckCheck, CheckCircle2, Download, Lock, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api, download } from "../api/client";
import type { Alarm, AlarmDetail, AlarmStatus, Page } from "../api/types";
import { useApi, useFacility, useToast } from "../components/hooks";
import { Card, EmptyState, ErrorState, Field, fmt, KeyValue, Loading, Modal, PageHeader, Pagination, SeverityBadge, StatusPill } from "../components/ui";

interface AlarmStats {
  by_status: Partial<Record<AlarmStatus, number>>;
  open_by_severity: Record<string, number>;
}

const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const NEXT_ACTION: Partial<Record<AlarmStatus, { action: "acknowledge" | "resolve" | "close"; label: string }>> = {
  ACTIVE: { action: "acknowledge", label: "Acknowledge" },
  ACKNOWLEDGED: { action: "resolve", label: "Resolve" },
  RESOLVED: { action: "close", label: "Close" },
};
const LIMIT = 25;

function loadActor(): string {
  try {
    return localStorage.getItem("yf.actor") ?? "operator";
  } catch {
    return "operator";
  }
}
function saveActor(v: string) {
  try {
    localStorage.setItem("yf.actor", v);
  } catch {
    /* storage unavailable */
  }
}

function fmtVal(v: number | null | undefined, unit?: string) {
  if (v === null || v === undefined) return "—";
  return `${fmt.n(v, 2)}${unit ? " " + unit : ""}`;
}

function AlarmDrawer({ alarmId, onClose, onChanged }: { alarmId: string; onClose: () => void; onChanged: () => void }) {
  const { notify } = useToast();
  const detail = useApi(() => api.get<AlarmDetail>(`/alarms/${alarmId}`), [alarmId]);
  const [actor, setActor] = useState(loadActor);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actorErr, setActorErr] = useState<string>();

  const act = async (action: string) => {
    if (!actor.trim()) {
      setActorErr("Operator name is required");
      return;
    }
    setActorErr(undefined);
    setBusy(true);
    try {
      const d = await api.post<AlarmDetail>(`/alarms/${alarmId}/${action}`, { actor: actor.trim(), note });
      saveActor(actor.trim());
      detail.setData(d);
      setNote("");
      notify("success", `${alarmId} → ${d.status}`);
      onChanged();
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const a = detail.data;
  const next = a ? NEXT_ACTION[a.status] : undefined;
  return (
    <Modal open title={`Alarm ${alarmId}`} onClose={onClose} wide
      footer={a && (
        <>
          <button className="btn-secondary" onClick={onClose}>Close panel</button>
          {(["ACTIVE", "ACKNOWLEDGED", "RESOLVED"] as AlarmStatus[]).map((from) => {
            const { action, label } = NEXT_ACTION[from]!;
            const enabled = next?.action === action;
            const Icon = action === "acknowledge" ? CheckCircle2 : action === "resolve" ? ShieldCheck : Lock;
            return (
              <button key={action} className={enabled ? "btn-primary" : "btn-secondary"} disabled={!enabled || busy}
                onClick={() => act(action)} title={enabled ? "" : `Only valid when status is ${from}`}>
                <Icon size={14} /> {label}
              </button>
            );
          })}
        </>
      )}>
      {detail.error ? (
        <ErrorState error={detail.error} onRetry={detail.reload} />
      ) : !a ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={a.severity} />
            <StatusPill status={a.status} />
            <span className="font-semibold">{fmt.label(a.alarm_type)}</span>
          </div>
          <p className="text-sm">{a.message}</p>
          <KeyValue items={[
            ["Facility", a.facility_id],
            ["Equipment", `${a.equipment_type} ${a.equipment_id}`],
            ["Raised", fmt.dt(a.raised_at)],
            ["Acknowledged", a.acknowledged_at ? `${fmt.dt(a.acknowledged_at)} by ${a.acknowledged_by}` : "—"],
            ["Resolved", a.resolved_at ? `${fmt.dt(a.resolved_at)} by ${a.resolved_by}` : "—"],
            ["Closed", a.closed_at ? `${fmt.dt(a.closed_at)} by ${a.closed_by}` : "—"],
            ["Related simulation", a.simulation_id ? <Link className="text-brand-600 hover:underline" to={`/simulation?id=${a.simulation_id}`}>{a.simulation_id}</Link> : "Live telemetry"],
          ]} />
          {a.anomaly && (
            <div className="rounded-md border border-line p-3">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-2">Related anomaly {a.anomaly.id}</h3>
              <KeyValue items={[
                ["Rule", <span className="font-mono text-xs">{a.anomaly.detection_rule}</span>],
                ["Condition", a.anomaly.rule_description],
                ["Sensor", a.anomaly.sensor_id ?? "—"],
                ["Observed", fmtVal(a.anomaly.observed_value, a.anomaly.unit)],
                ["Expected", fmtVal(a.anomaly.expected_value, a.anomaly.unit)],
                ["Threshold", fmtVal(a.anomaly.threshold, a.anomaly.unit)],
                ["Window", `${fmt.dt(a.anomaly.start_time)} → ${fmt.dt(a.anomaly.end_time)}`],
              ]} />
              {a.anomaly.evidence && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer text-ink-2">Evidence</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-stone-50 p-2 font-mono">{JSON.stringify(a.anomaly.evidence, null, 2)}</pre>
                </details>
              )}
            </div>
          )}
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Recommended action</h3>
            <p className="rounded-md border border-brand-100 bg-brand-50 p-3 text-sm">{a.recommended_action || "—"}</p>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-2">History</h3>
            <ol className="relative ml-2 border-l border-line">
              {a.events.map((e) => (
                <li key={e.id} className="mb-3 ml-4">
                  <span className="absolute -left-1.5 mt-1 h-3 w-3 rounded-full border-2 border-white bg-brand-500" />
                  <div className="text-sm">
                    <span className="font-medium">{e.from_status ? `${e.from_status} → ${e.to_status}` : `Raised (${e.to_status})`}</span>
                    <span className="ml-2 text-xs text-ink-2">{fmt.dt(e.timestamp)} · {e.actor}</span>
                  </div>
                  {e.note && <div className="text-xs text-ink-2">{e.note}</div>}
                </li>
              ))}
            </ol>
          </div>
          {next && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Operator" error={actorErr}>
                <input className="input" value={actor} onChange={(e) => setActor(e.target.value)} maxLength={60} />
              </Field>
              <Field label="Note (optional)">
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder={`Reason to ${next.action}`} />
              </Field>
            </div>
          )}
          {!next && <p className="text-xs text-ink-2">This alarm is closed; its lifecycle is complete.</p>}
        </div>
      )}
    </Modal>
  );
}

export default function Alarms() {
  const { facilityId } = useFacility();
  const { notify } = useToast();
  const [params, setParams] = useSearchParams();
  const simulationId = params.get("simulation_id") ?? "";
  const [status, setStatus] = useState<string>(simulationId ? "" : "ACTIVE");
  const [severity, setSeverity] = useState("");
  const [source, setSource] = useState<string>(simulationId ? "SIMULATION" : "LIVE");
  const [skip, setSkip] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  useEffect(() => {
    setSkip(0);
    setSelected(new Set());
  }, [status, severity, source, facilityId, simulationId]);

  const filters = { status, severity, source, facility_id: facilityId, simulation_id: simulationId };
  const list = useApi(() => api.get<Page<Alarm>>("/alarms", { ...filters, skip, limit: LIMIT }), [JSON.stringify(filters), skip]);
  const stats = useApi(() => api.get<AlarmStats>("/alarms/stats", { facility_id: facilityId, source: source || undefined }), [facilityId, source]);

  const refresh = () => {
    list.reload();
    stats.reload();
  };

  const activeRows = (list.data?.items ?? []).filter((a) => a.status === "ACTIVE");
  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });

  const bulkAck = async () => {
    const actor = loadActor();
    setBulkBusy(true);
    let ok = 0;
    const failed: string[] = [];
    for (const id of selected) {
      try {
        await api.post(`/alarms/${id}/acknowledge`, { actor, note: "Bulk acknowledge" });
        ok++;
      } catch (e) {
        failed.push(`${id}: ${(e as ApiError).message}`);
      }
    }
    setBulkBusy(false);
    setSelected(new Set());
    if (ok) notify("success", `Acknowledged ${ok} alarm(s) as ${actor}`);
    if (failed.length) notify("error", `Failed: ${failed.join("; ")}`);
    refresh();
  };

  const statusTab = (s: string, label: string, count?: number) => (
    <button key={s || "all"} onClick={() => setStatus(s)}
      className={`-mb-px border-b-2 px-3 py-2 text-sm ${status === s ? "border-brand-600 font-semibold text-brand-700" : "border-transparent text-ink-2 hover:text-ink"}`}>
      {label}
      {count !== undefined && <span className="ml-1.5 rounded-full bg-stone-100 px-1.5 text-xs num">{count}</span>}
    </button>
  );
  const bs = stats.data?.by_status ?? {};
  const total = Object.values(bs).reduce((a, b) => a + (b ?? 0), 0);

  return (
    <div>
      <PageHeader
        title="Alarm Management"
        subtitle="Lifecycle ACTIVE → ACKNOWLEDGED → RESOLVED → CLOSED. Every change is recorded in the alarm history."
        actions={
          <>
            <button className="btn-secondary" onClick={() => download("/alarms/export", { status, facility_id: facilityId, source: source || undefined, format: "csv" })}>
              <Download size={14} /> CSV
            </button>
            <button className="btn-secondary" onClick={() => download("/alarms/export", { status, facility_id: facilityId, source: source || undefined, format: "json" })}>
              <Download size={14} /> JSON
            </button>
            <button className="btn-secondary" onClick={refresh}><RefreshCw size={14} /> Refresh</button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {SEVERITIES.slice().reverse().map((s) => (
          <button key={s} onClick={() => setSeverity(severity === s ? "" : s)}
            className={`card flex items-center justify-between px-4 py-3 text-left ${severity === s ? "ring-2 ring-brand-500" : ""}`}>
            <SeverityBadge severity={s} />
            <span className="text-xl font-semibold num">{stats.data ? stats.data.open_by_severity[s] ?? 0 : "…"}</span>
            <span className="sr-only">open alarms</span>
          </button>
        ))}
      </div>

      {simulationId && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-brand-100 bg-brand-50 px-3 py-2 text-sm">
          Showing alarms from simulation <Link to={`/simulation?id=${simulationId}`} className="font-mono text-brand-700 hover:underline">{simulationId}</Link>
          <button className="btn-ghost ml-auto py-0.5" onClick={() => { params.delete("simulation_id"); setParams(params); setSource("LIVE"); setStatus("ACTIVE"); }}>Clear</button>
        </div>
      )}

      <Card bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-2">
          {statusTab("ACTIVE", "Active", bs.ACTIVE ?? 0)}
          {statusTab("ACKNOWLEDGED", "Acknowledged", bs.ACKNOWLEDGED ?? 0)}
          {statusTab("RESOLVED", "Resolved", bs.RESOLVED ?? 0)}
          {statusTab("CLOSED", "Closed", bs.CLOSED ?? 0)}
          {statusTab("", "All", total)}
          <div className="ml-auto flex items-center gap-2 py-2">
            <label className="flex items-center gap-1 text-xs text-ink-2">
              Source
              <select className="input w-auto py-1" value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="LIVE">Live telemetry</option>
                <option value="SIMULATION">Simulation</option>
                <option value="">All</option>
              </select>
            </label>
            <label className="flex items-center gap-1 text-xs text-ink-2">
              Severity
              <select className="input w-auto py-1" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                <option value="">All</option>
                {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
            <button className="btn-primary py-1" disabled={selected.size === 0 || bulkBusy} onClick={bulkAck}>
              <CheckCheck size={14} /> Acknowledge {selected.size || ""}
            </button>
          </div>
        </div>
        {list.error ? (
          <div className="p-4"><ErrorState error={list.error} onRetry={list.reload} /></div>
        ) : !list.data ? (
          <Loading />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No alarms match the filters" hint={status === "ACTIVE" ? "No active alarms in this scope." : undefined} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th className="w-8">
                    <input type="checkbox" aria-label="Select all active alarms on this page"
                      checked={activeRows.length > 0 && activeRows.every((a) => selected.has(a.id))}
                      disabled={activeRows.length === 0}
                      onChange={(e) => setSelected(e.target.checked ? new Set(activeRows.map((a) => a.id)) : new Set())} />
                  </th>
                  <th>Alarm</th><th>Raised</th><th>Severity</th><th>Status</th><th>Type</th><th>Equipment</th><th>Message</th><th>Source</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id} className="cursor-pointer" onClick={() => setOpenId(a.id)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${a.id}`} disabled={a.status !== "ACTIVE"} checked={selected.has(a.id)} onChange={() => toggle(a.id)} />
                    </td>
                    <td className="font-mono text-xs">{a.id}</td>
                    <td className="whitespace-nowrap num">{fmt.dt(a.raised_at)}</td>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td><StatusPill status={a.status} /></td>
                    <td className="whitespace-nowrap">{fmt.label(a.alarm_type)}</td>
                    <td className="whitespace-nowrap">{a.equipment_id}<div className="text-xs text-ink-2">{a.facility_id}</div></td>
                    <td className="max-w-md text-xs text-ink-2">{a.message}</td>
                    <td className="text-xs">{a.simulation_id ? <span className="font-mono">{a.simulation_id}</span> : "Live"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && <Pagination skip={skip} limit={LIMIT} total={list.data.total} onChange={setSkip} />}
      </Card>

      {openId && <AlarmDrawer alarmId={openId} onClose={() => setOpenId(null)} onChanged={refresh} />}
    </div>
  );
}
