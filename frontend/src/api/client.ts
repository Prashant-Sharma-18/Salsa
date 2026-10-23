/**
 * Thin fetch wrapper for the /api/v1 backend.
 * - Sends cookies (session is an HttpOnly cookie; nothing sensitive is kept in localStorage).
 * - Attaches the CSRF token to every state-changing request.
 * - Normalises error responses into ApiError.
 */

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

let csrfToken: string | null = null;
let portalCsrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function setPortalCsrfToken(token: string | null) {
  portalCsrfToken = token;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  portal?: boolean;
};

export async function api<T = unknown>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    const token = options.portal ? portalCsrfToken : csrfToken;
    if (token) headers["X-CSRF-Token"] = token;
  }
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: method === "GET" ? undefined : JSON.stringify(options.body ?? {}),
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server. Check your connection and try again.");
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const err = data?.error;
    throw new ApiError(
      response.status,
      err?.code ?? "http_error",
      err?.message ?? `Request failed (${response.status})`,
      err?.fields ?? {},
    );
  }
  return data as T;
}

/** Download a CSV through the authenticated session. */
export async function downloadFile(path: string, filename: string) {
  const response = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, data?.error?.code ?? "http_error", data?.error?.message ?? "Export failed");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function qs(params: Record<string, string | number | undefined | null | boolean>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "" && value !== false) search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}
