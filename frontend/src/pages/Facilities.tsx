import { Activity, Building2, Cpu, Database, GitFork, Pencil, Plus, RefreshCw, Trash2, Waves, Workflow } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Facility, FacilitySummary, OperatingMode, Severity } from "../api/types";
import { useApi, useFacility, useToast } from "../components/hooks";
import { Async, Card, EmptyState, ErrorState, Field, KeyValue, Loading, Modal, PageHeader, SeverityBadge, StatusPill, fmt } from "../components/ui";

type FormState = { name: string; location: string; description: string; status: Facility["status"]; operating_mode_id: string };
const EMPTY: FormState = { name: "", location: "", description: "", status: "OPERATIONAL", operating_mode_id: "" };
const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

const KIND_LINKS = [
  { kind: "pumps", label: "Pumps", icon: Cpu },
  { kind: "tanks", label: "Tanks", icon: Database },
  { kind: "valves", label: "Valves", icon: GitFork },
  { kind: "pipes", label: "Pipes", icon: Waves },
  { kind: "sensors", label: "Sensors", icon: Activity },
] as const;

function FacilityForm({ initial, modes, onCancel, onSaved, editId }: {
  initial: FormState; modes: OperatingMode[]; onCancel: () => void; onSaved: (f: Facility) => void; editId?: string;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const { notify } = useToast();

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (form.name.trim().length < 2) errs.name = "Name must be at least 2 characters.";
    if (form.name.length > 120) errs.name = "Name must be at most 120 characters.";
    if (form.location.length > 120) errs.location = "Location must be at most 120 characters.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    const body = { ...form, name: form.name.trim(), operating_mode_id: form.operating_mode_id || null };
    try {
      const saved = editId ? await api.put<Facility>(`/facilities/${editId}`, body) : await api.post<Facility>("/facilities", body);
      notify("success", `Facility ${saved.id} ${editId ? "updated" : "created"}.`);
      onSaved(saved);
    } catch (err) {
      const e2 = err as ApiError;
      const fe: Record<string, string> = {};
      e2.details?.forEach((d) => { if (d.field) fe[d.field] = d.message; });
      setErrors(fe);
      notify("error", e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <Field label="Name *" error={errors.name}>
        <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={120} />
      </Field>
      <Field label="Location" error={errors.location}>
        <input className="input" value={form.location} onChange={(e) => set("location", e.target.value)} maxLength={120} />
      </Field>
      <Field label="Description" error={errors.description}>
        <textarea className="input" rows={3} value={form.description} onChange={(e) => set("description", e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Status" error={errors.status}>
          <select className="input" value={form.status} onChange={(e) => set("status", e.target.value as FormState["status"])}>
            <option value="OPERATIONAL">Operational</option>
            <option value="MAINTENANCE">Maintenance</option>
            <option value="SHUTDOWN">Shutdown</option>
          </select>
        </Field>
        <Field label="Operating mode" error={errors.operating_mode_id}>
          <select className="input" value={form.operating_mode_id} onChange={(e) => set("operating_mode_id", e.target.value)}>
            <option value="">— None —</option>
            {modes.map((m) => (
              <option key={m.id} value={m.id}>{m.id} · {fmt.label(m.name)}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Saving…" : editId ? "Save changes" : "Create facility"}</button>
      </div>
    </form>
  );
}

function FacilityDetails({ facility, onEdit, onDelete }: { facility: Facility; onEdit: () => void; onDelete: () => void }) {
  const summary = useApi(() => api.get<FacilitySummary>(`/facilities/${facility.id}/summary`), [facility.id, facility.status, facility.name, facility.operating_mode_id]);
  const { setFacilityId } = useFacility();
  const nav = useNavigate();
  const go = (path: string) => {
    setFacilityId(facility.id);
    nav(path);
  };
  return (
    <Card
      title={<span className="flex items-center gap-2"><Building2 size={16} /> {facility.id} · {facility.name}</span>}
      subtitle={facility.location || "No location set"}
      actions={
        <>
          <button className="btn-secondary" onClick={onEdit}><Pencil size={14} /> Edit</button>
          <button className="btn-danger" onClick={onDelete}><Trash2 size={14} /> Delete</button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-2">{facility.description || "No description."}</p>
      <Async state={summary}>
        {(s) => (
          <div className="space-y-4">
            <KeyValue
              items={[
                ["Status", <StatusPill status={s.facility.status} />],
                ["Operating mode", s.operating_mode ? fmt.label(s.operating_mode) : "—"],
                ["Telemetry records", fmt.n(s.telemetry_records, 0)],
                ["Total storage", `${fmt.n(s.total_storage_m3, 0)} m³`],
                ["Installed pump flow", `${fmt.n(s.installed_pump_flow_m3h, 0)} m³/h`],
                ["Created", fmt.dt(s.facility.created_at)],
              ]}
            />
            <div>
              <div className="label">Open alarms (live)</div>
              {Object.keys(s.active_alarms_by_severity).length === 0 ? (
                <StatusPill status="NORMAL">No open alarms</StatusPill>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {SEVERITIES.filter((sv) => s.active_alarms_by_severity[sv]).map((sv) => (
                    <span key={sv} className="flex items-center gap-1"><SeverityBadge severity={sv} /> <span className="num text-sm">× {s.active_alarms_by_severity[sv]}</span></span>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="label">Equipment overview</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {KIND_LINKS.map(({ kind, label, icon: Icon }) => (
                  <button key={kind} className="card flex flex-col items-start px-3 py-2 text-left hover:border-brand-500" onClick={() => go(`/equipment/${kind}`)}>
                    <span className="flex items-center gap-1 text-xs text-ink-2"><Icon size={13} /> {label}</span>
                    <span className="text-lg font-semibold num">{s.counts[kind]}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn-secondary" onClick={() => go("/topology")}><Workflow size={14} /> View topology</button>
              <button className="btn-secondary" onClick={() => go("/monitoring")}><Activity size={14} /> Live monitoring</button>
              <Link className="btn-ghost" to="/alarms" onClick={() => setFacilityId(facility.id)}>Alarms →</Link>
            </div>
          </div>
        )}
      </Async>
    </Card>
  );
}

export default function Facilities() {
  const list = useApi(() => api.get<Facility[]>("/facilities"));
  const modes = useApi(() => api.get<OperatingMode[]>("/operating-modes"));
  const { reloadFacilities } = useFacility();
  const { notify } = useToast();
  const [selected, setSelected] = useState<string | null>(null);
  const [modal, setModal] = useState<{ mode: "create" } | { mode: "edit"; facility: Facility } | null>(null);
  const [confirm, setConfirm] = useState<Facility | null>(null);
  const [deleting, setDeleting] = useState(false);

  const facilities = list.data ?? [];
  const current = facilities.find((f) => f.id === selected) ?? facilities[0];

  const refresh = () => {
    list.reload();
    reloadFacilities();
  };

  async function doDelete(f: Facility) {
    setDeleting(true);
    try {
      await api.del(`/facilities/${f.id}`);
      notify("success", `Facility ${f.id} deleted.`);
      setConfirm(null);
      setSelected(null);
      refresh();
    } catch (e) {
      notify("error", (e as ApiError).message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Facility Management"
        subtitle="Facilities, their operating mode and equipment inventory."
        actions={
          <>
            <button className="btn-secondary" onClick={refresh}><RefreshCw size={14} /> Refresh</button>
            <button className="btn-primary" onClick={() => setModal({ mode: "create" })}><Plus size={14} /> New facility</button>
          </>
        }
      />
      {list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : list.data === undefined ? (
        <Loading />
      ) : facilities.length === 0 ? (
        <Card><EmptyState title="No facilities yet" hint="Create one, or run python -m scripts.generate_data." /></Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <Card title="Facilities" subtitle={`${facilities.length} registered`} bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr><th>ID</th><th>Name</th><th>Location</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {facilities.map((f) => (
                    <tr key={f.id} onClick={() => setSelected(f.id)} className={`cursor-pointer ${current?.id === f.id ? "bg-brand-50" : ""}`}>
                      <td className="font-mono text-xs">{f.id}</td>
                      <td className="font-medium">{f.name}</td>
                      <td className="text-ink-2">{f.location || "—"}</td>
                      <td><StatusPill status={f.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          {current && (
            <FacilityDetails facility={current} onEdit={() => setModal({ mode: "edit", facility: current })} onDelete={() => setConfirm(current)} />
          )}
        </div>
      )}

      <Modal open={modal !== null} title={modal?.mode === "edit" ? `Edit ${modal.facility.id}` : "New facility"} onClose={() => setModal(null)}>
        {modal && (
          <FacilityForm
            key={modal.mode === "edit" ? modal.facility.id : "new"}
            editId={modal.mode === "edit" ? modal.facility.id : undefined}
            initial={modal.mode === "edit" ? {
              name: modal.facility.name, location: modal.facility.location, description: modal.facility.description,
              status: modal.facility.status, operating_mode_id: modal.facility.operating_mode_id ?? "",
            } : EMPTY}
            modes={modes.data ?? []}
            onCancel={() => setModal(null)}
            onSaved={(f) => {
              setModal(null);
              setSelected(f.id);
              refresh();
            }}
          />
        )}
      </Modal>

      <Modal
        open={confirm !== null}
        title="Delete facility"
        onClose={() => setConfirm(null)}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
            <button className="btn-danger" disabled={deleting} onClick={() => confirm && doDelete(confirm)}>{deleting ? "Deleting…" : "Delete"}</button>
          </>
        }
      >
        <p className="text-sm">
          Delete <b>{confirm?.id} · {confirm?.name}</b>? Facilities that still contain equipment cannot be deleted; the server will explain what must be removed first.
        </p>
      </Modal>
    </div>
  );
}
