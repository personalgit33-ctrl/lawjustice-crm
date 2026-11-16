import type { LoginResponse, TwoFASetup, User } from './types';

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

const ls = {
  get(k: string) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch {} },
  del(k: string) { try { localStorage.removeItem(k); } catch {} },
};

export const tokens = {
  get access() { return ls.get('lj_access'); },
  get refresh() { return ls.get('lj_refresh'); },
  set(a: string, r?: string) { ls.set('lj_access', a); if (r) ls.set('lj_refresh', r); },
  clear() { ls.del('lj_access'); ls.del('lj_refresh'); },
};

export class ApiError extends Error {
  status: number; data: any;
  constructor(status: number, data: any) {
    super((data && (data.detail || data.error)) || firstFieldError(data) || `Ошибка ${status}`);
    this.status = status; this.data = data;
  }
}
function firstFieldError(d: any): string | null {
  if (!d || typeof d !== 'object') return null;
  for (const [k, v] of Object.entries(d)) { if (Array.isArray(v) && v.length) return `${k}: ${v[0]}`; if (typeof v === 'string') return v; }
  return null;
}

let onAuthLost: (() => void) | null = null;
export function setOnAuthLost(fn: () => void) { onAuthLost = fn; }

let refreshing: Promise<boolean> | null = null;
async function doRefresh(): Promise<boolean> {
  const r = tokens.refresh; if (!r) return false;
  if (!refreshing) refreshing = (async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/refresh/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh: r }) });
      if (!res.ok) return false;
      const d = await res.json(); tokens.set(d.access, d.refresh); return true;
    } catch { return false; } finally { setTimeout(() => { refreshing = null; }, 0); }
  })();
  return refreshing;
}

type Opts = { method?: string; body?: any; raw?: boolean; auth?: boolean };

async function raw(path: string, o: Opts = {}, retry = true): Promise<Response> {
  const headers: Record<string, string> = {};
  const isForm = typeof FormData !== 'undefined' && o.body instanceof FormData;
  if (o.body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  const a = tokens.access; if (a && o.auth !== false) headers['Authorization'] = `Bearer ${a}`;
  const url = path.startsWith('http') ? path : `${API_URL}/api/${path.replace(/^\//, '')}`;
  const res = await fetch(url, { method: o.method || (o.body !== undefined ? 'POST' : 'GET'), headers, body: o.body === undefined ? undefined : isForm ? o.body : JSON.stringify(o.body) });
  if (res.status === 401 && retry && o.auth !== false && tokens.refresh) {
    if (await doRefresh()) return raw(path, o, false);
    tokens.clear(); onAuthLost && onAuthLost();
  }
  return res;
}

export async function api<T = any>(path: string, o: Opts = {}): Promise<T> {
  let res: Response;
  try { res = await raw(path, o); } catch { throw new ApiError(0, { detail: 'Нет связи с сервером' }); }
  if (res.status === 204) return undefined as T;
  let data: any = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('json')) { try { data = await res.json(); } catch {} } else { try { data = await res.text(); } catch {} }
  if (!res.ok) throw new ApiError(res.status, typeof data === 'string' ? { detail: data.slice(0, 200) } : data);
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body: any = {}) => api<T>(p, { method: 'POST', body });
export const patch = <T = any>(p: string, body: any) => api<T>(p, { method: 'PATCH', body });
export const del = <T = any>(p: string) => api<T>(p, { method: 'DELETE' });
export const upload = <T = any>(p: string, fields: Record<string, string | Blob | number | undefined | null>) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) fd.append(k, v instanceof Blob ? v : String(v));
  return api<T>(p, { method: 'POST', body: fd });
};

/** Скачивание файла с JWT: fetch → blob → ссылка. */
export async function download(path: string, fallbackName = 'export') {
  const res = await raw(path);
  if (!res.ok) { let d: any = null; try { d = await res.json(); } catch {} throw new ApiError(res.status, d); }
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') || '';
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function fileUrl(u: string) { return u.startsWith('http') ? u : `${API_URL}${u}`; }

/** Шаг 1: логин и пароль. При 2FA бросает ApiError с data.otp_required / data.setup_required и data.mfa_token. */
export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await api<LoginResponse>('auth/login/', { method: 'POST', body: { username, password }, auth: false });
  tokens.set(res.access, res.refresh);
  return res;
}
/** Шаг 2: код из приложения или резервный код. */
export async function loginVerify(mfa_token: string, code: string): Promise<LoginResponse> {
  const res = await api<LoginResponse>('auth/login/verify/', { method: 'POST', body: { mfa_token, code }, auth: false });
  tokens.set(res.access, res.refresh);
  return res;
}
/** Обязательная настройка 2FA при входе (администратор, руководитель). */
export const enrollStart = (mfa_token: string) => api<TwoFASetup>('auth/2fa/enroll/start/', { method: 'POST', body: { mfa_token }, auth: false });
export async function enrollFinish(mfa_token: string, code: string): Promise<LoginResponse> {
  const res = await api<LoginResponse>('auth/2fa/enroll/finish/', { method: 'POST', body: { mfa_token, code }, auth: false });
  tokens.set(res.access, res.refresh);
  return res;
}
export const me = () => get<User>('auth/me/');
