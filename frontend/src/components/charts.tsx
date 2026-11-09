// Shared chart conventions (dataviz reference palette): fixed categorical order,
// thin 2px lines, recessive grid, crosshair tooltip, legend for >= 2 series.
//
// IMPORTANT: Recharts 2.x only recognises its own XAxis/YAxis/Tooltip/Legend/CartesianGrid
// as *direct* children of a chart. These helpers therefore return those elements and must be
// CALLED, not rendered as components:   {TimeAxis({})}  {ValueAxis({ unit: "bar" })}  {Grid({})}
import { ReactNode } from "react";
import { CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import { fmt } from "./ui";

export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const STATUS = { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" };
export const SEVERITY_COLOR: Record<string, string> = {
  LOW: "#86b6ef",
  MEDIUM: STATUS.warning,
  HIGH: STATUS.serious,
  CRITICAL: STATUS.critical,
};
export const GRID = "#e9e8e4";
export const AXIS = "#52514e";

export const axisProps = {
  stroke: GRID,
  tick: { fill: AXIS, fontSize: 11 },
  tickLine: false,
} as const;

export function TimeAxis({ dataKey = "t", interval }: { dataKey?: string; interval?: number }) {
  return <XAxis dataKey={dataKey} {...axisProps} tickFormatter={(v: string) => fmt.time(v)} minTickGap={40} interval={interval ?? "preserveStartEnd"} />;
}

export function ValueAxis({ unit, domain, width = 48 }: { unit?: string; domain?: [number | string, number | string]; width?: number }) {
  return (
    <YAxis
      {...axisProps}
      width={width}
      domain={domain ?? ["auto", "auto"]}
      tickFormatter={(v: number) => fmt.n(v, 1)}
      label={unit ? { value: unit, angle: -90, position: "insideLeft", fill: AXIS, fontSize: 11, dx: 4 } : undefined}
    />
  );
}

export function Grid(_opts: Record<string, never> = {}) {
  void _opts;
  return <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />;
}

export function ChartTooltip({ unit, timeLabel = true }: { unit?: string; timeLabel?: boolean }) {
  return (
    <Tooltip
      cursor={{ stroke: AXIS, strokeWidth: 1, strokeDasharray: "3 3" }}
      contentStyle={{ borderRadius: 6, border: "1px solid #e4e3df", fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,.08)" }}
      labelStyle={{ color: "#52514e", fontWeight: 600, marginBottom: 2 }}
      labelFormatter={(l: string) => (timeLabel ? fmt.time(l) : l)}
      formatter={(v: number | string, name: string) => [typeof v === "number" ? `${fmt.n(v, 2)}${unit ? " " + unit : ""}` : v, name]}
    />
  );
}

export function ChartLegend(_opts: Record<string, never> = {}) {
  void _opts;
  return <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: "#52514e", paddingTop: 4 }} />;
}

/** Fixed-height wrapper with an accessible description. */
export function ChartBox({ height = 240, label, children }: { height?: number; label: string; children: ReactNode }) {
  return (
    <div style={{ height }} role="img" aria-label={label} className="w-full">
      {children}
    </div>
  );
}

/** Zip a timestamp array and named series into Recharts rows. */
export function zipSeries(timestamps: string[], series: Record<string, (number | null)[]>) {
  return timestamps.map((t, i) => {
    const row: Record<string, number | string | null> = { t };
    for (const [k, v] of Object.entries(series)) row[k] = v[i] ?? null;
    return row;
  });
}
