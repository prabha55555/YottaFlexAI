import {
  Background, Controls, Edge, Handle, MarkerType, MiniMap, Node, NodeProps, Position, ReactFlow,
} from "@xyflow/react";
import { AlertOctagon, AlertTriangle, CheckCircle2, Cpu, Database, GitFork, RefreshCw, X } from "lucide-react";
import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Alarm, Page, Topology as TopologyT, TopologyEdge, TopologyNode } from "../api/types";
import { STATUS } from "../components/charts";
import { useApi, useFacility } from "../components/hooks";
import { Card, EmptyState, ErrorState, KeyValue, Loading, PageHeader, SeverityBadge, StatusPill, fmt } from "../components/ui";

const HEALTH_COLOR: Record<string, string> = { NORMAL: STATUS.good, WARNING: STATUS.warning, CRITICAL: STATUS.critical };
const HealthIcon = ({ h, size = 12 }: { h: string; size?: number }) =>
  h === "CRITICAL" ? <AlertOctagon size={size} color={STATUS.critical} aria-label="critical" /> :
  h === "WARNING" ? <AlertTriangle size={size} color="#b07a00" aria-label="warning" /> :
  <CheckCircle2 size={size} color={STATUS.good} aria-label="normal" />;

type EqData = { n: TopologyNode; selected: boolean };

function AlarmBadge({ count }: { count: number }) {
  if (!count) return null;
  return <span className="absolute -right-2 -top-2 rounded-full bg-critical px-1.5 text-[10px] font-bold text-white num">{count}</span>;
}

function PumpNode({ data }: NodeProps<Node<EqData>>) {
  const { n, selected } = data;
  return (
    <div className="relative flex flex-col items-center" title={`${n.id} · ${n.name}`}>
      <Handle type="target" position={Position.Left} className="!bg-stone-400" />
      <div
        className={`grid h-14 w-14 place-items-center rounded-full border-[3px] bg-white shadow-sm ${selected ? "ring-2 ring-brand-500 ring-offset-2" : ""}`}
        style={{ borderColor: HEALTH_COLOR[n.health] }}
      >
        <Cpu size={20} className="text-brand-700" />
      </div>
      <AlarmBadge count={n.active_alarms} />
      <div className="mt-1 flex items-center gap-1 text-[11px] font-semibold"><HealthIcon h={n.health} />{n.id}</div>
      <div className="max-w-[120px] truncate text-[10px] text-ink-2">{n.name}</div>
      <Handle type="source" position={Position.Right} className="!bg-stone-400" />
    </div>
  );
}

function TankNode({ data }: NodeProps<Node<EqData>>) {
  const { n, selected } = data;
  return (
    <div className="relative" title={`${n.id} · ${n.name}`}>
      <Handle type="target" position={Position.Left} className="!bg-stone-400" />
      <div
        className={`w-[118px] rounded-b-lg rounded-t-sm border-[3px] bg-white px-2 py-1.5 shadow-sm ${selected ? "ring-2 ring-brand-500 ring-offset-2" : ""}`}
        style={{ borderColor: HEALTH_COLOR[n.health] }}
      >
        <div className="flex items-center gap-1 text-[11px] font-semibold"><Database size={12} className="text-brand-700" /><HealthIcon h={n.health} />{n.id}</div>
        <div className="truncate text-[10px] text-ink-2">{n.name}</div>
        <div className="text-[10px] text-ink-3 num">{fmt.n(n.details.capacity_m3 as number, 0)} m³</div>
      </div>
      <AlarmBadge count={n.active_alarms} />
      <Handle type="source" position={Position.Right} className="!bg-stone-400" />
    </div>
  );
}

function ValveNode({ data }: NodeProps<Node<EqData>>) {
  const { n, selected } = data;
  const open = n.details.opening_pct as number;
  return (
    <div className="relative flex flex-col items-center" title={`${n.id} · ${n.name}`}>
      <Handle type="target" position={Position.Left} className="!bg-stone-400" />
      <div
        className={`grid h-9 w-9 rotate-45 place-items-center rounded-sm border-[3px] bg-white shadow-sm ${selected ? "ring-2 ring-brand-500 ring-offset-2" : ""}`}
        style={{ borderColor: HEALTH_COLOR[n.health] }}
      >
        <GitFork size={13} className="-rotate-45 text-ink-2" />
      </div>
      <AlarmBadge count={n.active_alarms} />
      <div className="mt-1.5 flex items-center gap-1 text-[10px] font-semibold"><HealthIcon h={n.health} size={11} />{n.id}</div>
      <div className="text-[10px] text-ink-2">
        {n.role !== "INLINE" && <span className="mr-1 rounded bg-stone-100 px-1 font-semibold">{n.role}</span>}
        <span className="num">{fmt.n(open, 0)}%</span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-stone-400" />
    </div>
  );
}

const nodeTypes = { PUMP: PumpNode, TANK: TankNode, VALVE: ValveNode };

type Sel = { kind: "node"; item: TopologyNode } | { kind: "edge"; item: TopologyEdge } | null;

function SelectionPanel({ sel, onClose, includeSim }: { sel: NonNullable<Sel>; onClose: () => void; includeSim: boolean }) {
  const id = sel.item.id;
  const alarms = useApi(
    () => api.get<Page<Alarm>>("/alarms", { equipment_id: id, status: "ACTIVE,ACKNOWLEDGED", source: includeSim ? undefined : "LIVE", limit: 50 }),
    [id, includeSim],
  );
  const kindPath = sel.kind === "edge" ? "pipes" : { PUMP: "pumps", TANK: "tanks", VALVE: "valves" }[sel.item.node_type];
  const it = sel.item;
  const details: [string, ReactNode][] =
    sel.kind === "edge"
      ? [
          ["Flow direction", `${sel.item.from_node_id} → ${sel.item.to_node_id}`],
          ["Length", `${fmt.n(sel.item.length_m)} m`],
          ["Diameter", `${fmt.n(sel.item.diameter_mm, 0)} mm`],
          ["Max flow", `${fmt.n(sel.item.max_flow_m3h)} m³/h`],
          ["Pressure rating", `${fmt.n(sel.item.max_pressure_bar)} bar`],
          ["Restriction", `${fmt.n(sel.item.restriction_pct)} %`],
          ["Status", <StatusPill status={sel.item.status} />],
          ["Valid connection", sel.item.valid ? "Yes" : "No — references a missing node"],
        ]
      : [
          ["Type", `${sel.item.node_type}${sel.item.role ? ` (${sel.item.role})` : ""}`],
          ["Status", <StatusPill status={sel.item.status} />],
          ...Object.entries(sel.item.details).map(([k, v]) => [fmt.label(k), typeof v === "number" ? fmt.n(v, 3) : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v ?? "—")] as [string, ReactNode]),
        ];
  return (
    <Card
      title={<span className="flex items-center gap-1.5"><HealthIcon h={it.health} size={14} />{it.id} · {it.name}</span>}
      subtitle={`Health: ${it.health}${it.top_severity ? ` (top severity ${it.top_severity})` : ""}`}
      actions={<button className="btn-ghost px-1.5" onClick={onClose} aria-label="Close"><X size={14} /></button>}
    >
      <div className="space-y-4">
        <KeyValue items={details} />
        <div>
          <div className="label">Sensors</div>
          {it.sensors.length === 0 ? (
            <span className="text-xs text-ink-3">No sensors mounted</span>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {it.sensors.map((s) => (
                <span key={s.id} className="rounded border border-line bg-stone-50 px-1.5 py-0.5 font-mono text-[11px]" title={`${s.id} · ${s.sensor_type} (${s.unit})`}>
                  {s.tag} <span className="text-ink-3">{s.unit}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="label">Open alarms {includeSim ? "(incl. simulation)" : "(live)"}</div>
          {alarms.error ? (
            <ErrorState error={alarms.error} onRetry={alarms.reload} />
          ) : !alarms.data ? (
            <Loading />
          ) : alarms.data.items.length === 0 ? (
            <span className="text-xs text-ink-3">No open alarms on this equipment.</span>
          ) : (
            <ul className="space-y-1.5">
              {alarms.data.items.map((a) => (
                <li key={a.id} className="rounded border border-line p-2 text-xs">
                  <div className="flex items-center gap-2"><SeverityBadge severity={a.severity} /><span className="font-mono">{a.id}</span><StatusPill status={a.status} /></div>
                  <div className="mt-1 text-ink-2">{a.message}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex gap-2">
          <Link className="btn-secondary" to={`/equipment/${kindPath}`}>Open {kindPath}</Link>
          <Link className="btn-ghost" to="/alarms">Alarm management →</Link>
        </div>
      </div>
    </Card>
  );
}

function Legend() {
  const item = (c: string, l: string) => (
    <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full border-[3px] bg-white" style={{ borderColor: c }} />{l}</span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
      <span className="flex items-center gap-1"><Cpu size={13} /> Pump</span>
      <span className="flex items-center gap-1"><Database size={13} /> Tank</span>
      <span className="flex items-center gap-1"><GitFork size={13} /> Valve (INLET / OUTLET = boundary)</span>
      {item(STATUS.good, "Normal")}
      {item(STATUS.warning, "Warning")}
      {item(STATUS.critical, "Critical / invalid")}
      <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2 border-stone-400" /> → Pipe, arrow = flow direction</span>
      <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2 border-dashed border-critical" /> Invalid connection</span>
    </div>
  );
}

export default function Topology() {
  const { concreteId } = useFacility();
  const [includeSim, setIncludeSim] = useState(false);
  const [sel, setSel] = useState<Sel>(null);
  const topo = useApi(() => (concreteId ? api.get<TopologyT>(`/topology/${concreteId}`, { include_simulation_alarms: includeSim }) : Promise.resolve(undefined as unknown as TopologyT)), [concreteId, includeSim]);
  const t = topo.data;

  const { nodes, edges } = useMemo(() => {
    if (!t) return { nodes: [] as Node<EqData>[], edges: [] as Edge[] };
    const nodes: Node<EqData>[] = t.nodes.map((n) => ({
      id: n.id,
      type: n.node_type,
      position: n.position,
      data: { n, selected: sel?.kind === "node" && sel.item.id === n.id },
    }));
    const edges: Edge[] = t.edges.map((e) => {
      const color = !e.valid ? STATUS.critical : e.health === "CRITICAL" ? STATUS.critical : e.health === "WARNING" ? "#d49a00" : "#8a8984";
      const selected = sel?.kind === "edge" && sel.item.id === e.id;
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        animated: e.status === "IN_SERVICE" && e.valid,
        label: e.restriction_pct > 0 ? `${e.id} · ${fmt.n(e.restriction_pct)}% restr.` : e.active_alarms ? `${e.id} · ${e.active_alarms} alarm(s)` : undefined,
        labelStyle: { fontSize: 10, fill: "#52514e" },
        style: { stroke: color, strokeWidth: selected ? 4 : e.health !== "NORMAL" ? 3 : 2, strokeDasharray: e.valid ? undefined : "6 4" },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        data: { e },
      };
    });
    return { nodes, edges };
  }, [t, sel]);

  const v = t?.validation;
  return (
    <div>
      <PageHeader
        title="Plant Topology"
        subtitle={`Network graph built from database records for ${concreteId || "—"} (NetworkX on the backend). Click equipment or pipes for details.`}
        actions={
          <>
            <label className="flex items-center gap-1.5 text-sm text-ink-2">
              <input type="checkbox" checked={includeSim} onChange={(e) => setIncludeSim(e.target.checked)} /> Include simulation alarms
            </label>
            <button className="btn-secondary" onClick={topo.reload}><RefreshCw size={14} /> Refresh</button>
          </>
        }
      />
      {topo.error ? (
        <ErrorState error={topo.error} onRetry={topo.reload} />
      ) : !t ? (
        <Loading label="Building topology…" />
      ) : t.nodes.length === 0 ? (
        <Card><EmptyState title="This facility has no equipment yet" hint="Add pumps, tanks, valves and pipes in Master Data." /></Card>
      ) : (
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="space-y-3">
            <Card bodyClass="p-0">
              <div className="h-[620px] w-full">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  fitView
                  minZoom={0.15}
                  nodesDraggable
                  nodesConnectable={false}
                  onNodeClick={(_, n) => setSel({ kind: "node", item: (n.data as EqData).n })}
                  onEdgeClick={(_, e) => setSel({ kind: "edge", item: (e.data as { e: TopologyEdge }).e })}
                  onPaneClick={() => setSel(null)}
                >
                  <Background gap={20} color="#e4e3df" />
                  <Controls showInteractive={false} />
                  <MiniMap pannable zoomable nodeColor={(n) => HEALTH_COLOR[(n.data as EqData).n.health]} />
                </ReactFlow>
              </div>
            </Card>
            <Legend />
          </div>
          <div className="space-y-4">
            {sel && <SelectionPanel key={sel.item.id} sel={sel} onClose={() => setSel(null)} includeSim={includeSim} />}
            {v && (
              <Card title="Topology validation" subtitle={`${t.summary.nodes} nodes · ${t.summary.edges} pipes · ${t.summary.sensors} sensors`}>
                <div className="space-y-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill status={v.is_valid ? "OK" : "CRITICAL"}>{v.is_valid ? "Valid network" : "Invalid network"}</StatusPill>
                    <span className="text-xs text-ink-2 num">{v.error_count} errors · {v.warning_count} warnings · {v.is_dag ? "acyclic" : "contains cycles"}</span>
                  </div>
                  <KeyValue
                    items={[
                      ["Connected components", `${v.components.length} (sizes ${v.components.map((c) => c.size).join(", ")})`],
                      ["Supply inlets", v.sources.length],
                      ["Demand outlets", v.sinks.length],
                      ["Supply→demand paths", v.supply_to_demand_paths.length],
                      ["Unreachable nodes", v.unreachable_nodes.length ? v.unreachable_nodes.join(", ") : "None"],
                    ]}
                  />
                  <div>
                    <div className="label">Issues</div>
                    {v.issues.length === 0 ? (
                      <StatusPill status="OK">No topology issues found</StatusPill>
                    ) : (
                      <ul className="max-h-64 space-y-1 overflow-y-auto">
                        {v.issues.map((i, k) => (
                          <li key={k} className="rounded border border-line p-1.5 text-xs">
                            <span className={`mr-1 font-semibold ${i.severity === "ERROR" ? "text-critical" : "text-amber-700"}`}>{i.severity}</span>
                            <span className="font-mono">{i.code}</span> · {i.message}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  {v.supply_to_demand_paths.length > 0 && (
                    <details>
                      <summary className="cursor-pointer text-xs text-ink-2">Show supply→demand paths</summary>
                      <ul className="mt-1 space-y-1 font-mono text-[11px]">
                        {v.supply_to_demand_paths.map((p) => <li key={p.source + p.sink}>{p.path.join(" → ")}</li>)}
                      </ul>
                    </details>
                  )}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
