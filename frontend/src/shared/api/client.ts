import type { Client } from 'openapi-fetch';
import type { paths } from './schema';
import { actingEpoch, actingHeaders } from '../acting';
import { lang } from '../i18n';
import { getAccessToken, refreshSession } from './session';

/** Endpoints where a 401 means "wrong credentials" or "no session", never "refresh and retry". */
const NO_RETRY = new Set(['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/logout']);

/**
 * Bearer token from memory, and the UI language, so the server can write
 * explanations and messages in the person's language.
 */
function withBearer(request: Request): Request {
  const token = getAccessToken();
  const headers = new Headers(request.headers);
  headers.set('Accept-Language', lang.peek());
  if (token) headers.set('Authorization', `Bearer ${token}`);
  // Helper Mode: the family's headers on every request for that family (not on sign-in or switching).
  const path = new URL(request.url, window.location.origin).pathname;
  const acting = path.startsWith('/v1/helper/') || path.startsWith('/v1/auth/') ? null : actingHeaders();
  if (acting) for (const [name, value] of Object.entries(acting)) headers.set(name, value);
  return new Request(request, { headers });
}

/**
 * fetch used by the typed client: attaches the in-memory bearer token and, on
 * a 401, does one single-flight refresh and retries the request once.
 */
async function authFetch(request: Request): Promise<Response> {
  const path = new URL(request.url, window.location.origin).pathname;
  const retryable = !NO_RETRY.has(path);
  const spare = retryable ? request.clone() : null;
  const epoch = actingEpoch();
  // An answer for a family the helper has already left is never shown or stored for the next one.
  const checked = (response: Response): Response => {
    if (epoch !== actingEpoch()) throw new DOMException('Another family is open now', 'AbortError');
    return response;
  };
  const response = checked(await fetch(withBearer(request)));
  if (response.status !== 401 || !spare) return response;
  const outcome = await refreshSession();
  if (outcome !== 'ok') return response;
  return checked(await fetch(withBearer(spare)));
}

interface Init {
  params?: { path?: Record<string, unknown>; query?: Record<string, unknown>; header?: Record<string, unknown> };
  body?: unknown;
  headers?: Record<string, string>;
  parseAs?: 'json' | 'text' | 'blob' | 'arrayBuffer';
}

/**
 * One request, with the subset of openapi-fetch's behaviour this app uses: `{name}` path parameters,
 * scalar or array query parameters (`a=1&a=2`; null and undefined left out), header parameters, a JSON or
 * FormData body, and `parseAs`. Returns `{ data }` or `{ error }` with the response, as openapi-fetch does;
 * a network failure throws (`call()` turns it into a value).
 */
async function send(method: string, path: string, init: Init = {}): Promise<{ data?: unknown; error?: unknown; response: Response }> {
  const { params = {}, body, headers, parseAs = 'json' } = init;
  let url = path.replace(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(String(params.path?.[name])));
  const search = Object.entries(params.query ?? {})
    .flatMap(([name, value]) => (value == null ? [] : [value].flat().map((one) => `${name}=${encodeURIComponent(String(one))}`)))
    .join('&');
  if (search) url += `?${search}`;
  const merged = new Headers({ Accept: 'application/json' });
  for (const [name, value] of Object.entries({ ...headers, ...params.header })) if (value != null) merged.set(name, String(value));
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    // FormData: the browser writes the multipart Content-Type with its boundary.
    if (body instanceof FormData) payload = body;
    else {
      payload = JSON.stringify(body);
      merged.set('Content-Type', 'application/json');
    }
  }
  const response = await authFetch(new Request(url, { method, headers: merged, body: payload, credentials: 'same-origin', redirect: 'follow' }));
  const length = response.headers.get('Content-Length');
  if (response.status === 204 || method === 'HEAD' || (length === '0' && !response.headers.get('Transfer-Encoding')?.includes('chunked'))) {
    return { response };
  }
  if (response.ok) {
    if (parseAs !== 'json') return { data: await response[parseAs](), response };
    const raw = await response.text();
    return { data: raw ? JSON.parse(raw) : undefined, response };
  }
  let error: unknown = await response.text();
  try {
    error = JSON.parse(error as string);
  } catch {
    // not JSON: keep the text
  }
  return { error, response };
}

const method =
  (name: string) =>
  (path: string, init?: Init): ReturnType<typeof send> =>
    send(name, path, init);

/**
 * Typed API client (same origin), with the types of openapi-fetch and the
 * generated schema. Usage:
 *
 *   import { api } from '../shared/api/client';
 *   import { call } from '../shared/api/problem';
 *   const res = await call(api.GET('/v1/auth/me'));
 */
export const api = {
  GET: method('GET'),
  POST: method('POST'),
  PUT: method('PUT'),
  PATCH: method('PATCH'),
  DELETE: method('DELETE'),
} as unknown as Client<paths>;
