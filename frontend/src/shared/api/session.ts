import { signal } from '@preact/signals';
import type { ActiveMembership, AuthOut, AuthUser, Membership } from './types';

/**
 * Session state. The access token is held in this module's memory only: never
 * localStorage, sessionStorage, IndexedDB or a cookie readable by script. The
 * refresh token is an httpOnly SameSite cookie the browser sends to
 * /v1/auth/refresh; script never sees it. A reload therefore calls refresh
 * once to get a new access token (restoreSession in ./auth.ts).
 */
export type SessionState =
  | { status: 'restoring' }
  | { status: 'signed-out'; reason: 'none' | 'expired' | 'logout' | 'offline' | 'error' }
  | {
      status: 'signed-in';
      user: AuthUser;
      active: ActiveMembership;
      memberships: Membership[];
    };

export const session = signal<SessionState>({ status: 'restoring' });

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

/** Signed in on this phone only (an offline sign-in opened the local data): no token until the network is back. */
export function isLocalSession(): boolean {
  return session.peek().status === 'signed-in' && accessToken === null;
}

/** Forget the access token but keep the session (idle lock); the next request refreshes it from the cookie. */
export function dropAccessToken(): void {
  accessToken = null;
}

const endHandlers = new Set<() => void>();

/**
 * Register a function that wipes in-memory state when the session ends or the
 * person changes (logout, expiry, a login in another tab). Returns an unsubscribe.
 */
export function onSessionEnd(handler: () => void): () => void {
  endHandlers.add(handler);
  return () => endHandlers.delete(handler);
}

export function applyAuth(out: AuthOut): void {
  const previous = session.peek();
  if (previous.status === 'signed-in' && previous.user.id !== out.user.id) runEndHandlers();
  accessToken = out.access_token;
  session.value = {
    status: 'signed-in',
    user: out.user,
    active: out.active,
    memberships: out.memberships,
  };
}

/**
 * An offline sign-in: the PIN opened this person's data on the phone, but the
 * server cannot be reached. The app runs from local data with no token; the
 * first request after the network returns refreshes the session from the
 * cookie (or, without one, asks the person to sign in).
 */
export function applyLocal(user: AuthUser, active: ActiveMembership, memberships: Membership[]): void {
  const previous = session.peek();
  if (previous.status === 'signed-in' && previous.user.id !== user.id) runEndHandlers();
  accessToken = null;
  session.value = { status: 'signed-in', user, active, memberships };
}

/** Wipe in-memory state (drafts, answers, lists) without ending the session: the idle lock. */
export function wipeMemory(): void {
  runEndHandlers();
}

export function clearAuth(reason: 'none' | 'expired' | 'logout' | 'offline' | 'error'): void {
  const wasSignedIn = session.peek().status === 'signed-in';
  accessToken = null;
  session.value = { status: 'signed-out', reason };
  if (wasSignedIn) runEndHandlers();
}

function runEndHandlers(): void {
  for (const handler of endHandlers) {
    try {
      handler();
    } catch {
      // one failing cleanup must not stop the others
    }
  }
}

export const CSRF_HEADER = { 'X-Requested-With': 'rahat' } as const;

export type RefreshOutcome = 'ok' | 'signed-out' | 'offline' | 'error';

let inFlight: Promise<RefreshOutcome> | null = null;

/**
 * Refresh the access token. Single-flight inside the tab, and serialised across
 * tabs with the Web Locks API, so two tabs never present the same rotating
 * refresh cookie (which reuse detection would treat as theft).
 */
export function refreshSession(): Promise<RefreshOutcome> {
  if (!inFlight) {
    const run = async (): Promise<RefreshOutcome> =>
      typeof navigator !== 'undefined' && navigator.locks
        ? await navigator.locks.request('rahat-auth-refresh', () => doRefresh())
        : doRefresh();
    inFlight = run().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

async function doRefresh(): Promise<RefreshOutcome> {
  let response: Response;
  try {
    response = await fetch('/v1/auth/refresh', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...CSRF_HEADER },
    });
  } catch {
    return typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'error';
  }
  if (response.ok) {
    try {
      applyAuth((await response.json()) as AuthOut);
      return 'ok';
    } catch {
      return 'error';
    }
  }
  if (response.status === 401 || response.status === 403) {
    clearAuth('expired');
    return 'signed-out';
  }
  return 'error';
}

// Cross-tab: a logout in one tab signs out every tab; a login in another tab
// replaces the cookie, so this tab drops its state and picks up the new session.
type AuthMessage = { type: 'logout' } | { type: 'login' };
const channel: BroadcastChannel | null =
  typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('rahat-auth');

export function broadcast(message: AuthMessage): void {
  channel?.postMessage(message);
}

channel?.addEventListener('message', (event: MessageEvent<AuthMessage>) => {
  if (event.data?.type === 'logout') {
    clearAuth('logout');
  } else if (event.data?.type === 'login') {
    clearAuth('none');
    session.value = { status: 'restoring' };
    void refreshSession().then((outcome) => {
      if (outcome !== 'ok' && session.peek().status === 'restoring') clearAuth('none');
    });
  }
});
