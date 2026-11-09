// Central API client. Every page talks to the backend through this module.

export class ApiError extends Error {
  status: number;
  details: { field?: string; message: string }[];
  constructor(status: number, message: string, details: { field?: string; message: string }[] = []) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

const BASE = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_BASE ?? "/api";

type Query = Record<string, string | number | boolean | null | undefined>;

export function qs(params?: Query): string {
  if (!params) return "";
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

function parseError(status: number, body: unknown): ApiError {
  const b = body as { detail?: unknown };
  const d = b?.detail;
  if (typeof d === "string") return new ApiError(status, d);
  if (Array.isArray(d)) {
    return new ApiError(status, d.map((x: { msg?: string }) => x.msg).join("; "));
  }
  if (d && typeof d === "object") {
    const o = d as { message?: string; errors?: { field?: string; message: string }[]; error?: string };
    return new ApiError(status, o.message ?? o.error ?? `Request failed (${status})`, o.errors ?? []);
  }
  return new ApiError(status, `Request failed (${status})`);
}

async function request<T>(method: string, path: string, body?: unknown, params?: Query): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(params)}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the backend API. Is it running on port 8000?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const json = text ? JSON.parse(text) : undefined;
  if (!res.ok) throw parseError(res.status, json);
  return json as T;
}

export const api = {
  get: <T>(path: string, params?: Query) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown, params?: Query) => request<T>("POST", path, body ?? {}, params),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: (path: string) => request<void>("DELETE", path),
  /** Absolute URL for file downloads (CSV/JSON exports). */
  url: (path: string, params?: Query) => `${BASE}${path}${qs(params)}`,
};

export function download(path: string, params?: Query) {
  const a = document.createElement("a");
  a.href = api.url(path, params);
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
