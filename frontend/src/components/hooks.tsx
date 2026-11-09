import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { CheckCircle2, AlertOctagon, X } from "lucide-react";
import { api } from "../api/client";
import type { Facility } from "../api/types";

/** Fetch helper with loading / error / reload state. `deps` re-trigger the fetch. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fnRef
      .current()
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

// ------------------------------------------------------------- toasts
type Toast = { id: number; kind: "success" | "error"; message: string };
const ToastCtx = createContext<{ notify: (kind: Toast["kind"], message: string) => void }>({ notify: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ notify }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`card flex items-start gap-2 px-3 py-2.5 text-sm shadow-lg ${t.kind === "error" ? "border-red-300" : "border-emerald-300"}`}>
            {t.kind === "error" ? <AlertOctagon size={16} className="mt-0.5 shrink-0 text-critical" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" />}
            <span className="flex-1">{t.message}</span>
            <button className="text-ink-3 hover:text-ink" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

// ------------------------------------------------------- facility scope
type FacilityCtxT = {
  facilities: Facility[];
  facilityId: string; // "" = all facilities
  setFacilityId: (id: string) => void;
  /** A concrete facility for pages that need exactly one (falls back to the first). */
  concreteId: string;
  reloadFacilities: () => void;
};
const FacilityCtx = createContext<FacilityCtxT>({ facilities: [], facilityId: "", setFacilityId: () => {}, concreteId: "", reloadFacilities: () => {} });

export function FacilityProvider({ children }: { children: ReactNode }) {
  const [facilityId, setFacilityIdState] = useState<string>(() => {
    try {
      return localStorage.getItem("yf.facility") ?? "";
    } catch {
      return "";
    }
  });
  const { data, reload } = useApi(() => api.get<Facility[]>("/facilities"));
  const facilities = data ?? [];
  const setFacilityId = (id: string) => {
    setFacilityIdState(id);
    try {
      localStorage.setItem("yf.facility", id);
    } catch {
      /* storage unavailable */
    }
  };
  const valid = facilityId && facilities.some((f) => f.id === facilityId) ? facilityId : "";
  const concreteId = valid || facilities[0]?.id || "";
  return (
    <FacilityCtx.Provider value={{ facilities, facilityId: valid, setFacilityId, concreteId, reloadFacilities: reload }}>
      {children}
    </FacilityCtx.Provider>
  );
}
export const useFacility = () => useContext(FacilityCtx);
