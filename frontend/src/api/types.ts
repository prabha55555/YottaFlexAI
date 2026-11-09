// Types mirroring backend response schemas (backend/app/schemas).

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlarmStatus = "ACTIVE" | "ACKNOWLEDGED" | "RESOLVED" | "CLOSED";

export interface Page<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface Facility {
  id: string;
  name: string;
  location: string;
  description: string;
  status: "OPERATIONAL" | "MAINTENANCE" | "SHUTDOWN";
  operating_mode_id: string | null;
  created_at: string | null;
}

export interface OperatingMode {
  id: string;
  name: string;
  description: string;
  demand_factor: number;
  pump_speed_factor: number;
}

export interface FacilitySummary {
  facility: Facility;
  counts: Record<"pumps" | "tanks" | "valves" | "pipes" | "sensors", number>;
  telemetry_records: number;
  active_alarms_by_severity: Partial<Record<Severity, number>>;
  total_storage_m3: number;
  installed_pump_flow_m3h: number;
  operating_mode: string | null;
}

export interface Pump {
  id: string; facility_id: string; name: string; rated_flow_m3h: number; shutoff_head_m: number; curve_k: number;
  speed_pct: number; rated_power_kw: number; best_efficiency: number; health_factor: number; available: boolean;
  status: string;
}
export interface Tank {
  id: string; facility_id: string; name: string; capacity_m3: number; height_m: number; elevation_m: number;
  initial_level_pct: number; setpoint_pct: number; high_alarm_pct: number; low_alarm_pct: number; status: string;
}
export interface Valve {
  id: string; facility_id: string; name: string; valve_type: string; role: "INLINE" | "INLET" | "OUTLET";
  opening_pct: number; resistance_full_open: number; boundary_flow_m3h: number | null; status: string;
}
export interface Pipe {
  id: string; facility_id: string; name: string; from_node_type: string; from_node_id: string; to_node_type: string;
  to_node_id: string; length_m: number; diameter_mm: number; friction_factor: number; max_flow_m3h: number;
  max_pressure_bar: number; restriction_pct: number; status: string;
}
export interface Sensor {
  id: string; facility_id: string; name: string; tag: string; equipment_type: string; equipment_id: string;
  sensor_type: "FLOW" | "PRESSURE" | "LEVEL"; measurement_point: string; unit: string; min_range: number;
  max_range: number; accuracy_pct: number; status: string;
}

export interface TelemetryRow {
  id: number; sensor_id: string; timestamp: string; value: number | null; derived_value: number | null;
  derived_unit: string | null; source: string;
}

export interface SensorMeta {
  tag: string; name: string; unit: string; sensor_type: string; equipment_id: string; min_range: number; max_range: number;
}
export interface SeriesResponse {
  timestamps: string[];
  series: Record<string, (number | null)[]>;
  sensors: Record<string, SensorMeta>;
  simulated: boolean;
}

export interface SnapshotReading {
  sensor_id: string; tag: string; name: string; sensor_type: string; unit: string; equipment_type: string;
  equipment_id: string; measurement_point: string; value: number | null; derived_value: number | null;
  derived_unit: string | null; min_range: number; max_range: number; quality: "GOOD" | "SUSPECT" | "BAD"; reason: string;
}
export interface Snapshot {
  timestamp: string | null; start: string | null; end: string | null; readings: SnapshotReading[]; simulated: boolean;
}

export interface Anomaly {
  id: string; facility_id: string; equipment_type: string; equipment_id: string; sensor_id: string | null;
  anomaly_type: string; category: "PROCESS" | "SENSOR" | "OPERATIONAL"; severity: Severity; detection_rule: string;
  rule_description: string; start_time: string; end_time: string; detected_at: string; observed_value: number | null;
  expected_value: number | null; threshold: number | null; unit: string; evidence: Record<string, unknown> | null;
  recommended_action: string; source: "TELEMETRY_SCAN" | "SIMULATION"; simulation_id: string | null;
}

export interface AlarmEvent {
  id: number; from_status: string | null; to_status: string; actor: string; note: string; timestamp: string;
}
export interface Alarm {
  id: string; facility_id: string; equipment_type: string; equipment_id: string; anomaly_id: string | null;
  simulation_id: string | null; alarm_type: string; severity: Severity; status: AlarmStatus; message: string;
  recommended_action: string; raised_at: string; acknowledged_at: string | null; acknowledged_by: string | null;
  resolved_at: string | null; resolved_by: string | null; closed_at: string | null; closed_by: string | null;
}
export interface AlarmDetail extends Alarm {
  events: AlarmEvent[];
  anomaly: Anomaly | null;
}

export interface TopologyNode {
  id: string; node_type: "PUMP" | "TANK" | "VALVE"; role?: string; facility_id: string; name: string; status: string;
  details: Record<string, unknown>; position: { x: number; y: number }; health: "NORMAL" | "WARNING" | "CRITICAL";
  active_alarms: number; top_severity: Severity | null;
  sensors: { id: string; tag: string; sensor_type: string; unit: string; measurement_point?: string }[];
}
export interface TopologyEdge extends Pipe {
  source: string; target: string; health: "NORMAL" | "WARNING" | "CRITICAL"; active_alarms: number;
  top_severity: Severity | null; valid: boolean; sensors: { id: string; tag: string; sensor_type: string; unit: string }[];
}
export interface TopologyIssue { severity: "ERROR" | "WARNING"; code: string; equipment_id: string; message: string }
export interface Topology {
  facility_id: string;
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  summary: Record<string, number>;
  validation: {
    is_valid: boolean; error_count: number; warning_count: number; issues: TopologyIssue[];
    components: { id: number; nodes: string[]; size: number }[]; is_dag: boolean; sources: string[]; sinks: string[];
    unreachable_nodes: string[]; supply_to_demand_paths: { source: string; sink: string; path: string[] }[];
  };
}

export interface MassBalance {
  facility_id: string; hours: number; tolerance_pct: number; total_inflow_m3: number; total_outflow_m3: number;
  storage_change_m3: number; residual_m3: number; estimated_leakage_m3: number; balance_error_pct: number | null;
  status: "BALANCED" | "WARNING" | "EXCEPTION" | "INSUFFICIENT_DATA";
  classification: "OK" | "PROCESS_IMBALANCE" | "MEASUREMENT_FAULT" | "INSUFFICIENT_DATA";
  suspect_sensors: string[];
  inflows: { valve_id: string; sensor_id: string; volume_m3: number }[];
  outflows: { valve_id: string; sensor_id: string; volume_m3: number }[];
  tanks: { tank_id: string; sensor_id: string; start_level_pct: number; end_level_pct: number; volume_change_m3: number }[];
  line_losses: { pump_id: string; pipe_id: string; upstream_volume_m3: number; downstream_volume_m3: number;
    loss_m3: number; loss_pct: number | null; sensor_suspect: boolean }[];
  start?: string; end?: string;
  windows?: (Pick<MassBalance, "total_inflow_m3" | "total_outflow_m3" | "storage_change_m3" | "residual_m3" |
    "estimated_leakage_m3" | "balance_error_pct" | "status" | "classification" | "suspect_sensors"> &
    { start: string; end: string })[];
  exceptions?: unknown[];
}

export interface SimulationKpis {
  total_inflow_m3: number; total_outflow_m3: number; demand_m3: number; demand_served_pct: number | null;
  true_leak_m3: number; overflow_m3: number; storage_change_m3: number; pump_energy_kwh: number;
  specific_energy_kwh_per_m3: number | null; measured_balance_error_pct: number | null; mass_balance_status: string;
  anomaly_count: number; critical_anomalies: number;
}
export interface SimulationSummary {
  kpis: SimulationKpis;
  anomalies_by_type: Record<string, number>;
  anomalies_by_severity: Record<string, number>;
  lines: Record<string, { mean_flow_m3h: number; mean_delivered_m3h: number; min_flow_m3h: number;
    max_discharge_pressure_bar: number; mean_efficiency: number; energy_kwh: number; leak_volume_m3: number }>;
  tanks: Record<string, { start_level_pct: number; end_level_pct: number; min_level_pct: number;
    max_level_pct: number; overflow_m3: number }>;
}
export interface SimulationTimeseries {
  timestamps: string[];
  lines: Record<string, Record<"q_up" | "q_down" | "p_suction" | "p_discharge" | "head" | "efficiency", (number | null)[]>>;
  tanks: Record<string, { level_pct: (number | null)[]; volume_m3: (number | null)[] }>;
  inlets: Record<string, { q: (number | null)[] }>;
  outlets: Record<string, { q: (number | null)[]; demand: (number | null)[] }>;
}
export interface SimulationListItem {
  id: string; facility_id: string; name: string; scenario: string; status: "COMPLETED" | "FAILED"; seed: number;
  steps: number; step_minutes: number; baseline_simulation_id: string | null; input_hash: string | null;
  duration_ms: number | null; created_at: string; summary: SimulationSummary | null;
  validation_errors: { field: string; message: string }[] | null;
}
export interface SimulationDetail extends SimulationListItem {
  start_time: string;
  original_config: Record<string, unknown> | null;
  modified_parameters: { user: Record<string, unknown>; resolved: Record<string, unknown>; fault_start_step: number } | null;
  effective_config: Record<string, unknown> | null;
  mass_balance: { measured: MassBalance; true_closure: Record<string, number> } | null;
  timeseries: SimulationTimeseries | null;
  assumptions: string[] | null;
}
export interface SimulationParameters {
  operating_mode_id?: string;
  demand_factor?: number;
  pump_speeds?: Record<string, number>;
  pump_availability?: Record<string, boolean>;
  valve_openings?: Record<string, number>;
  tank_initial_levels?: Record<string, number>;
  flow_demand?: Record<string, number>;
  pipe_restrictions?: Record<string, number>;
  pipe_leaks?: Record<string, number>;
  pump_health?: Record<string, number>;
  sensor_faults?: Record<string, string>;
}
export interface ScenarioInfo { id: string; description: string; preset: SimulationParameters | null }
export interface Comparison {
  baseline_id: string; modified_id: string; baseline_scenario: string; modified_scenario: string;
  kpis: Record<string, { baseline: number | string | null; modified: number | string | null; delta: number | null; delta_pct: number | null }>;
  lines: Record<string, Record<string, { baseline: number | null; modified: number | null }>>;
  tanks: Record<string, Record<string, { baseline: number | null; modified: number | null }>>;
  warnings: string[];
  anomalies_by_type: { baseline: Record<string, number>; modified: Record<string, number> };
  timeseries: { timestamps: string[]; baseline: SimulationTimeseries; modified: SimulationTimeseries; length: number };
}

export interface DashboardSummary {
  facility_id: string | null;
  totals: { facilities: number; equipment: number; pumps: number; tanks: number; valves: number; pipes: number;
    sensors: number; active_alarms: number; critical_alarms: number; critical_anomalies: number; telemetry_records: number };
  equipment_health: Record<string, { NORMAL: number; WARNING: number; CRITICAL: number }>;
  plant_status: { facility_id: string; name: string; status: string; operating_mode: string | null; open_alarms: number;
    critical_alarms: number; condition: "NORMAL" | "WARNING" | "ALARM" }[];
  trend_facility_id: string | null;
  trends: { timestamps: string[]; inflow: (number | null)[]; outflow: (number | null)[];
    discharge_pressure: (number | null)[]; suction_pressure: (number | null)[] } | null;
  tank_levels: { tank_id: string; name: string; facility_id: string; level_pct: number | null; capacity_m3: number;
    volume_m3: number | null; high_alarm_pct: number; low_alarm_pct: number }[];
  latest_timestamp: string | null;
  recent_simulations: { id: string; facility_id: string; scenario: string; status: string; created_at: string;
    anomalies: number | null; balance_status: string | null }[];
}

export interface Analytics {
  facility_id: string;
  period: { start: string | null; end: string | null };
  equipment_health: { pump_id: string; name: string; rated_flow_m3h: number; mean_flow_m3h: number | null;
    utilisation_pct: number | null; performance_index: number | null; performance_index_p5: number | null;
    health: "GOOD" | "WARNING" | "CRITICAL" }[];
  flow_analysis: { pump_id: string; pipe_id: string; mean_upstream_m3h: number | null; mean_downstream_m3h: number | null;
    max_upstream_m3h: number | null; line_loss_pct: number | null; pipe_capacity_m3h: number }[];
  pressure_analysis: { pump_id: string; mean_discharge_bar: number | null; max_discharge_bar: number | null;
    min_discharge_bar: number | null; mean_suction_bar: number | null; pipe_rating_bar: number | null;
    max_pct_of_rating: number | null }[];
  tank_utilisation: { tank_id: string; name: string; capacity_m3: number; mean_level_pct: number | null;
    min_level_pct: number | null; max_level_pct: number | null; time_above_high_pct: number | null;
    time_below_low_pct: number | null }[];
  anomaly_distribution: ({ anomaly_type: string; total: number; TELEMETRY_SCAN: number; SIMULATION: number } & Record<Severity, number>)[];
  alarm_trend: ({ bucket: string } & Record<Severity, number>)[];
  simulation_performance: { scenario: string; runs: number; completed: number; failed: number; success_rate_pct: number;
    mean_duration_ms: number | null; mean_anomalies: number | null; mean_energy_kwh: number | null;
    mean_demand_served_pct: number | null }[];
}

export interface ConfusionCounts { tp: number; fp: number; tn: number; fn: number; precision: number | null;
  recall: number | null; f1_score: number | null }
export interface Evaluation {
  available: boolean; message?: string; window_hours: number; windows: number; seed: number; scale: string;
  per_type: Record<string, ConfusionCounts & { units: number; labels: number; predictions: number }>;
  overall: ConfusionCounts & { accuracy: number };
  event_level: Record<string, { labels: number; detected: number; event_recall: number | null;
    mean_latency_min: number | null; severity_agreement: number | null; unmatched_predictions: string[];
    details: { scenario_id: string; equipment_id: string; sub_type: string; detected: boolean; anomaly_ids: string[];
      latency_min: number | null; expected_severity: string; detected_severity: string | null }[] }>;
  sensor_faults_labelled_as_process: { scenario_id: string; sensor_id: string; anomaly_id: string }[];
  method: string;
}
export interface DataQuality {
  dataset: { seed: number; scale: string; fingerprint: string; counts: Record<string, number> } | null;
  primary_key_integrity_pct: number; primary_key_errors: number; foreign_key_integrity_pct: number;
  foreign_key_errors: number; duplicate_count: number; duplicates: Record<string, number>; missing_value_pct: number;
  missing_values: number; topology_valid_facilities: number; topology_total_facilities: number;
  simulation_success_rate_pct: number | null; simulation_runs: number; mass_balance_mean_abs_error_pct: number | null;
  mass_balance_facility_totals: { facility_id: string; balance_error_pct: number | null; status: string;
    classification: string; residual_m3: number; total_inflow_m3: number }[];
}

export interface ValidationReport {
  primary_keys: { checked_records: number; error_count: number; errors: { table: string; id: string; error: string; message?: string }[]; duplicate_telemetry_keys: number };
  foreign_keys: { checked_relationships: number; error_count: number; errors: { table: string; id: string | null; field: string; message: string }[] };
  duplicates: Record<string, number>;
  missing_values: { telemetry_rows: number; telemetry_missing_values: number; telemetry_missing_pct: number;
    missing_by_sensor: { sensor_id: string; missing: number }[]; required_field_nulls: Record<string, number> };
  topology: { facilities: { facility_id: string; is_valid: boolean; errors: number; warnings: number; components: number;
    issues: TopologyIssue[] }[]; valid_facilities: number; total: number };
  tank_capacity: { violation_count: number; violations: { tank_id: string; type: string; message: string; count?: number;
    max_level_pct?: number }[]; high_level_tanks: { tank_id: string; samples_at_or_above_high_alarm: number }[] };
  mass_balance: { failures: { facility_id: string; start: string; end: string; balance_error_pct: number; status: string;
    residual_m3: number; classification: string; message: string }[]; failure_count: number;
    facility_totals: DataQuality["mass_balance_facility_totals"]; mean_abs_balance_error_pct: number | null };
  sensor_readings: { sensors_with_invalid_readings: number; out_of_range_readings: number; missing_readings: number;
    items: { sensor_id: string; tag: string; facility_id: string; sensor_type: string; range: [number, number];
      out_of_range: number; missing: number; min_value: number | null; max_value: number | null; readings: number }[] };
  simulations: { total_runs: number; completed: number; failed: number; success_rate_pct: number | null;
    errors: { simulation_id: string; type: string; errors: { field: string; message: string }[] }[] };
  alarm_history: { alarms_without_history: number; events: number };
}

export interface NegativeCase {
  case_id: string; title: string; description: string; check: string; expected_error_code: string;
  validation_status: "FAILED" | "PASSED"; detected_as_expected: boolean;
  errors: { code: string; message: string; [k: string]: unknown }[]; evidence: Record<string, unknown>; fixture: string;
}
export interface NegativeScenarios { cases: NegativeCase[]; total: number; caught: number; note: string }
