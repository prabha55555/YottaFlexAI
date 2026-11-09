import { AlertCircle, AlertOctagon, AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Inbox, Loader2, RefreshCw, X } from "lucide-react";
import { ReactNode, useEffect } from "react";
import type { Severity } from "../api/types";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-ink-2 mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, subtitle, actions, children, className = "", bodyClass = "p-4" }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-2 px-4 pt-3.5 pb-2">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="text-xs text-ink-2 mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, unit, hint, tone = "default", icon }: {
  label: string; value: ReactNode; unit?: string; hint?: ReactNode; tone?: "default" | "good" | "warning" | "critical"; icon?: ReactNode;
}) {
  const bar = { default: "bg-brand-500", good: "bg-good", warning: "bg-warning", critical: "bg-critical" }[tone];
  return (
    <div className="card relative overflow-hidden px-4 py-3">
      <span className={`absolute left-0 top-0 h-full w-1 ${bar}`} aria-hidden />
      <div className="flex items-center justify-between text-xs font-medium text-ink-2">
        <span>{label}</span>
        {icon}
      </div>
      <div className="mt-1 text-2xl font-semibold num">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-2">{unit}</span>}
      </div>
      {hint && <div className="text-xs text-ink-2 mt-0.5">{hint}</div>}
    </div>
  );
}

const SEV_STYLE: Record<Severity, { cls: string; Icon: typeof Info }> = {
  LOW: { cls: "bg-sky-50 text-sky-800 border-sky-200", Icon: Info },
  MEDIUM: { cls: "bg-amber-50 text-amber-900 border-amber-300", Icon: AlertTriangle },
  HIGH: { cls: "bg-orange-50 text-orange-900 border-orange-300", Icon: AlertCircle },
  CRITICAL: { cls: "bg-red-50 text-red-800 border-red-300", Icon: AlertOctagon },
};

/** Severity always shown as icon + label (never colour alone). */
export function SeverityBadge({ severity }: { severity: Severity | string | null | undefined }) {
  if (!severity) return <span className="text-ink-3">—</span>;
  const s = SEV_STYLE[severity as Severity] ?? SEV_STYLE.LOW;
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-semibold ${s.cls}`}>
      <s.Icon size={12} aria-hidden />
      {severity}
    </span>
  );
}

const PILL: Record<string, string> = {
  ACTIVE: "bg-red-50 text-red-800 border-red-200",
  ACKNOWLEDGED: "bg-amber-50 text-amber-900 border-amber-200",
  RESOLVED: "bg-emerald-50 text-emerald-800 border-emerald-200",
  CLOSED: "bg-stone-100 text-stone-600 border-stone-200",
  COMPLETED: "bg-emerald-50 text-emerald-800 border-emerald-200",
  FAILED: "bg-red-50 text-red-800 border-red-200",
  NORMAL: "bg-emerald-50 text-emerald-800 border-emerald-200",
  GOOD: "bg-emerald-50 text-emerald-800 border-emerald-200",
  OK: "bg-emerald-50 text-emerald-800 border-emerald-200",
  BALANCED: "bg-emerald-50 text-emerald-800 border-emerald-200",
  OPERATIONAL: "bg-emerald-50 text-emerald-800 border-emerald-200",
  RUNNING: "bg-emerald-50 text-emerald-800 border-emerald-200",
  IN_SERVICE: "bg-emerald-50 text-emerald-800 border-emerald-200",
  WARNING: "bg-amber-50 text-amber-900 border-amber-200",
  SUSPECT: "bg-amber-50 text-amber-900 border-amber-200",
  MAINTENANCE: "bg-amber-50 text-amber-900 border-amber-200",
  CRITICAL: "bg-red-50 text-red-800 border-red-200",
  ALARM: "bg-red-50 text-red-800 border-red-200",
  BAD: "bg-red-50 text-red-800 border-red-200",
  EXCEPTION: "bg-red-50 text-red-800 border-red-200",
  SHUTDOWN: "bg-stone-100 text-stone-700 border-stone-200",
  PROCESS_IMBALANCE: "bg-red-50 text-red-800 border-red-200",
  MEASUREMENT_FAULT: "bg-amber-50 text-amber-900 border-amber-200",
};

export function StatusPill({ status, children }: { status: string | null | undefined; children?: ReactNode }) {
  if (!status) return <span className="text-ink-3">—</span>;
  const cls = PILL[status] ?? "bg-stone-50 text-stone-700 border-stone-200";
  const good = ["NORMAL", "GOOD", "OK", "BALANCED", "COMPLETED", "RESOLVED", "OPERATIONAL", "RUNNING", "IN_SERVICE"].includes(status);
  const bad = ["CRITICAL", "ALARM", "BAD", "EXCEPTION", "FAILED", "ACTIVE", "PROCESS_IMBALANCE"].includes(status);
  const Icon = good ? CheckCircle2 : bad ? AlertOctagon : AlertTriangle;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${cls}`}>
      <Icon size={11} aria-hidden />
      {children ?? status.replace(/_/g, " ")}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-2" role="status">
      <Loader2 className="animate-spin" size={16} /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error | string; onRetry?: () => void }) {
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-6 text-center text-sm text-red-800" role="alert">
      <AlertOctagon size={20} />
      <div>{msg}</div>
      {onRetry && (
        <button className="btn-secondary mt-1" onClick={onRetry}>
          <RefreshCw size={14} /> Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 py-10 text-center text-ink-2">
      <Inbox size={22} className="text-ink-3" />
      <div className="text-sm font-medium text-ink">{title}</div>
      {hint && <div className="text-xs">{hint}</div>}
    </div>
  );
}

/** Wraps the standard loading/error/empty handling of an async section. */
export function Async<T>({ state, children, empty, isEmpty }: {
  state: { data: T | undefined; error: Error | null; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode; empty?: ReactNode; isEmpty?: (d: T) => boolean;
}) {
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return <Loading />;
  if (isEmpty && isEmpty(state.data)) return <>{empty ?? <EmptyState title="No data" />}</>;
  return <>{children(state.data)}</>;
}

export function Pagination({ skip, limit, total, onChange }: { skip: number; limit: number; total: number; onChange: (skip: number) => void }) {
  const page = Math.floor(skip / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex items-center justify-between px-3 py-2 text-xs text-ink-2">
      <span className="num">
        {total === 0 ? "0 records" : `${skip + 1}–${Math.min(skip + limit, total)} of ${total.toLocaleString()}`}
      </span>
      <div className="flex items-center gap-1">
        <button className="btn-ghost px-2" disabled={page <= 1} onClick={() => onChange(Math.max(0, skip - limit))} aria-label="Previous page">
          <ChevronLeft size={14} />
        </button>
        <span className="num">Page {page} / {pages}</span>
        <button className="btn-ghost px-2" disabled={page >= pages} onClick={() => onChange(skip + limit)} aria-label="Next page">
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer, wide }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 pt-16" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card w-full ${wide ? "max-w-3xl" : "max-w-lg"} shadow-xl`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button className="btn-ghost px-1.5" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, error, children, hint }: { label: string; error?: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && !error && <span className="mt-0.5 block text-[11px] text-ink-3">{hint}</span>}
      {error && <span className="mt-0.5 block text-[11px] text-critical">{error}</span>}
    </label>
  );
}

export function SimulatedBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-brand-100 bg-brand-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-brand-700" title="All telemetry is synthetic; no physical hardware is connected.">
      Simulated data
    </span>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-2">{k}</dt>
          <dd className="num break-words">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export const fmt = {
  n: (v: number | null | undefined, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 })),
  pct: (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`),
  dt: (s: string | null | undefined) => (s ? new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z").toLocaleString(undefined, { timeZone: "UTC", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "—"),
  time: (s: string) => new Date(s.endsWith("Z") ? s : s + "Z").toLocaleString(undefined, { timeZone: "UTC", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }),
  label: (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()),
};
