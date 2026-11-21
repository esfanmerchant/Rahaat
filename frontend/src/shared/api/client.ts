import createClient from 'openapi-fetch';
import type { paths } from './schema';
import { getAccessToken, refreshSession } from './session';

/** Endpoints where a 401 means "wrong credentials" or "no session", never "refresh and retry". */
const NO_RETRY = new Set(['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/logout']);

function withBearer(request: Request): Request {
  const token = getAccessToken();
  if (!token) return request;
  const headers = new Headers(request.headers);
  headers.set('Authorization', `Bearer ${token}`);
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
  const response = await fetch(withBearer(request));
  if (response.status !== 401 || !spare) return response;
  const outcome = await refreshSession();
  if (outcome !== 'ok') return response;
  return fetch(withBearer(spare));
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
