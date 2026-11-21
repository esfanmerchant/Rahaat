import createClient from 'openapi-fetch';
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

/**
 * Typed API client (same origin). Usage:
 *
 *   import { api } from '../shared/api/client';
 *   import { call } from '../shared/api/problem';
 *   const res = await call(api.GET('/v1/auth/me'));
 */
export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'same-origin',
  headers: { Accept: 'application/json' },
  fetch: authFetch,
});
