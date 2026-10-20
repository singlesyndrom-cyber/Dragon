/** Запросы к API. На сервере — напрямую в бэкенд, в браузере — через /api (rewrites в next.config). */

const SERVER_API = process.env.API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function errorText(data: any, status: number): string {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) {
    const first = d[0];
    const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : "";
    return field ? `Проверьте поле «${field}»: ${first.msg}` : String(first.msg);
  }
  if (status === 401) return "Войдите в аккаунт";
  if (status === 403) return "Недостаточно прав";
  if (status === 404) return "Не найдено";
  return `Ошибка сервера (${status})`;
}

/** Серверный GET для публичных страниц. Ошибка или недоступный API -> null, страница покажет пустое состояние. */
export async function sget<T = any>(path: string): Promise<T | null> {
  try {
    const r = await fetch(SERVER_API + path, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export const TOKEN_KEY = "dragon_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData };

/** Браузерный запрос с токеном. 204 -> null, ошибка -> ApiError с понятным текстом. */
export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const r = await fetch("/api" + path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (r.status === 204) return null as T;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(errorText(data, r.status), r.status);
  return data as T;
}
