import { online } from '../network';

/** RFC 7807 problem body, as every API error returns it (PLAN 6.11). */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string | null;
  code: string;
  request_id: string;
  errors?: ReadonlyArray<{ field: string; message: string; code: string }> | null;
}

export type FailureKind =
  | 'offline' // no network: show the offline state, keep the work
  | 'network' // network exists but the request failed (timeout, DNS, reset)
  | 'unauthenticated' // 401 after one refresh attempt: sign in again
  | 'forbidden' // 403: show permission denied, never hide the cause
  | 'not_found' // 404
  | 'conflict' // 409
  | 'validation' // 422: repairable; see problem.errors
  | 'locked' // 423: too many tries
  | 'rate_limited' // 429
  | 'server'; // 5xx or anything unexpected

export interface ApiFailure {
  kind: FailureKind;
  status?: number;
  problem?: Problem;
}

export type Result<T> = { ok: true; data: T } | { ok: false; failure: ApiFailure };

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { status?: unknown }).status === 'number' &&
    typeof (value as { title?: unknown }).title === 'string'
  );
}

export function kindForStatus(status: number): FailureKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 400 || status === 422) return 'validation';
  if (status === 423) return 'locked';
  if (status === 429) return 'rate_limited';
  return 'server';
}

export function failureFromResponse(response: Response, body: unknown): ApiFailure {
  const failure: ApiFailure = { kind: kindForStatus(response.status), status: response.status };
  if (isProblem(body)) failure.problem = body;
  return failure;
}

export function failureFromThrown(): ApiFailure {
  return { kind: online.peek() ? 'network' : 'offline' };
}

/**
 * Wrap an openapi-fetch call so every outcome is a value, never a throw:
 *
 *   const res = await call(api.GET('/v1/auth/me'));
 *   if (!res.ok) return <ScreenState kind={screenKindFor(res.failure)} ... />;
 */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<Result<T>> {
  try {
    const { data, error, response } = await request;
    if (response.ok) return { ok: true, data: data as T };
    return { ok: false, failure: failureFromResponse(response, error) };
  } catch {
    return { ok: false, failure: failureFromThrown() };
  }
}

/** Which screen state a failure maps to (docs/DESIGN.md, state checklist). */
export function screenKindFor(failure: ApiFailure): 'offline' | 'denied' | 'not_found' | 'error' {
  switch (failure.kind) {
    case 'offline':
      return 'offline';
    case 'forbidden':
      return 'denied';
    case 'not_found':
      return 'not_found';
    default:
      return 'error';
  }
}
