import { getAccessToken } from '../../shared/api/session';
import { activeRole } from '../scam';

/**
 * Real calls for the Challenge Lab. Each call is made with fetch and recorded as it happened: method, path,
 * who made it, the status, the time, the (trimmed) request and response, and the server's request id.
 * Nothing here fakes a result. Calls made as a demo account use that account's own token with
 * credentials omitted, so the page's own session and cookie are never touched.
 */
export interface Trace {
  actor: string;
  method: string;
  path: string;
  status: number;
  ms: number;
  request?: unknown;
  response: unknown;
  requestId?: string | undefined;
}

export interface Actor {
  /** A bearer token, or null for no authentication. */
  token: string | null;
  name: string;
}

export type Query = Record<string, string | number | undefined>;

const SECRET_KEYS = new Set(['secret', 'access_token', 'refresh_token', 'key']);

/** Tokens, secrets and keys never appear in the log, even though the log is only on this page. */
function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, SECRET_KEYS.has(k) && typeof v === 'string' ? '(hidden)' : redact(v)]));
  }
  return value;
}

export function trimmed(value: unknown, max = 1400): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 1) ?? '';
  return text.length > max ? `${text.slice(0, max)}\n… trimmed, ${text.length - max} more characters` : text;
}

const uuid = (): string => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

export async function send(method: 'GET' | 'POST' | 'PUT', path: string, o: { as: Actor; body?: unknown; query?: Query; raw?: BodyInit }): Promise<{ trace: Trace; data: unknown }> {
  const qs = o.query
    ? `?${Object.entries(o.query)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')}`
    : '';
  const url = `${path}${qs === '?' ? '' : qs}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (o.as.token) headers['Authorization'] = `Bearer ${o.as.token}`;
  if (o.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['Idempotency-Key'] = uuid();
  const started = performance.now();
  const trace: Trace = { actor: o.as.name, method, path: url, status: 0, ms: 0, response: null };
  if (o.body !== undefined) trace.request = redact(o.body);
  let data: unknown = null;
  try {
    const res = await fetch(url, { method, headers, credentials: 'omit', ...(o.body !== undefined ? { body: JSON.stringify(o.body) } : {}) });
    trace.status = res.status;
    trace.requestId = res.headers.get('x-request-id') ?? undefined;
    const text = await res.text();
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    trace.response = redact(data);
  } catch (e) {
    trace.response = { error: e instanceof Error ? e.message : 'The request did not reach the server.' };
  }
  trace.ms = Math.round(performance.now() - started);
  return { trace, data };
}

export interface DemoAccount {
  label: string;
  kind: string;
  role: string;
  tenant_slug: string;
  identifier: string;
  secret: string;
}

let accountsCache: Promise<DemoAccount[] | null> | null = null;
/** The demo accounts, or null when the server is not in demo mode. */
export function demoAccounts(): Promise<DemoAccount[] | null> {
  accountsCache ??= fetch('/v1/demo/accounts', { credentials: 'omit' })
    .then((r) => (r.ok ? r.json() : null))
    .then((j: { accounts?: DemoAccount[] } | null) => j?.accounts ?? null)
    .catch(() => null);
  return accountsCache;
}

const tokens = new Map<string, { token: string; at: number }>();

/** Sign in as a demo account with its own token. The page's session and cookies are not used or changed. */
export async function demoActor(role: string, tenant = 'sindh-relief', pick?: (a: DemoAccount) => boolean): Promise<{ actor: Actor; trace?: Trace } | null> {
  const list = await demoAccounts();
  const account = list?.find((a) => a.role === role && a.tenant_slug === tenant && (pick ? pick(a) : true));
  if (!account) return null;
  const hit = tokens.get(account.identifier);
  if (hit && Date.now() - hit.at < 9 * 60_000) return { actor: { token: hit.token, name: `demo ${account.role} (${account.identifier})` } };
  const { trace, data } = await send('POST', '/v1/auth/login', { as: { token: null, name: `demo ${account.role}` }, body: { identifier: account.identifier, secret: account.secret } });
  const token = (data as { access_token?: string } | null)?.access_token;
  if (!token) return { actor: { token: null, name: `demo ${account.role}` }, trace };
  tokens.set(account.identifier, { token, at: Date.now() });
  return { actor: { token, name: `demo ${account.role} (${account.identifier})` }, trace };
}

/** The page's own session as an actor, read only: the token is used, never replaced. */
export function pageActor(): Actor {
  return { token: getAccessToken(), name: `you (${activeRole() || 'signed in'})` };
}

export const isRole = (...roles: string[]): boolean => roles.includes(activeRole());
