import { hasChosenLang, isLang, setLang } from '../i18n';
import { online } from '../network';
import { deletePref, getPref, setPref } from '../prefs';
import { api } from './client';
import { call, type ApiFailure, type Result } from './problem';
import {
  applyAuth,
  broadcast,
  clearAuth,
  CSRF_HEADER,
  getAccessToken,
  refreshSession,
  session,
} from './session';
import type { AuthOut, AuthUser, LoginBody, Role } from './types';

export { onSessionEnd, session, type SessionState } from './session';

const STAFF_ROLES: ReadonlySet<string> = new Set(['officer', 'admin', 'auditor']);

export function isStaffRole(role: string): boolean {
  return STAFF_ROLES.has(role);
}

/** Where a role lands after login: citizen and helper on '/', staff on '/staff'. */
export function homePathFor(role: string): '/' | '/staff' {
  return isStaffRole(role) ? '/staff' : '/';
}

/**
 * Citizens: a language picked on this device wins, otherwise use the profile's.
 * Staff: never; the console runs in English and LTR.
 */
function adoptProfileLanguage(user: AuthUser, role: string): void {
  if (isStaffRole(role) || hasChosenLang() || !isLang(user.lang)) return;
  setLang(user.lang, { persist: false });
}

/**
 * Call once at startup. Restores the session from the refresh cookie, so a
 * reload keeps the person signed in without storing any token in the browser.
 */
export async function restoreSession(): Promise<void> {
  session.value = { status: 'restoring' };

  // A logout that could not reach the server (offline) is finished first, so a
  // shared phone never silently restores the previous person's session.
  if ((await getPref('pendingLogout')) === true) {
    if (await serverLogout()) {
      await deletePref('pendingLogout');
      clearAuth('logout');
    } else {
      clearAuth(online.peek() ? 'error' : 'offline');
    }
    return;
  }

  const outcome = await refreshSession();
  const now = session.peek();
  if (outcome === 'ok' && now.status === 'signed-in') {
    adoptProfileLanguage(now.user, now.active.role);
    return;
  }
  // No cookie on a first visit is not an "expired" session.
  if (outcome === 'offline') clearAuth('offline');
  else if (outcome === 'error') clearAuth('error');
  else clearAuth('none');
}

// Retry the restore when the network comes back, if it failed for lack of one.
online.subscribe((isOnline) => {
  const now = session.peek();
  if (isOnline && now.status === 'signed-out' && now.reason === 'offline') void restoreSession();
});

export type LoginResult = { ok: true; role: Role } | { ok: false; failure: ApiFailure };

export async function login(body: LoginBody): Promise<LoginResult> {
  const result: Result<AuthOut> = await call(api.POST('/v1/auth/login', { body }));
  if (!result.ok) return result;
  void deletePref('pendingLogout'); // a fresh login supersedes an unfinished logout
  applyAuth(result.data);
  adoptProfileLanguage(result.data.user, result.data.active.role);
  broadcast({ type: 'login' });
  return { ok: true, role: result.data.active.role };
}

export async function switchTenant(tenantId: string, role?: Role): Promise<Result<AuthOut>> {
  const body = role === undefined ? { tenant_id: tenantId } : { tenant_id: tenantId, role };
  const result = await call(api.POST('/v1/auth/switch', { body }));
  if (result.ok) applyAuth(result.data);
  return result;
}

async function serverLogout(): Promise<boolean> {
  const token = getAccessToken();
  try {
    const response = await fetch('/v1/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { ...CSRF_HEADER, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    // 401 means there was no session left to end: the goal is met.
    return response.ok || response.status === 401;
  } catch {
    return false;
  }
}

/**
 * Sign out. Memory is cleared at once, even offline; if the server cannot be
 * reached, the logout is finished on the next start (see restoreSession).
 */
export async function logout(): Promise<void> {
  const reached = await serverLogout();
  if (!reached) await setPref('pendingLogout', true);
  clearAuth('logout');
  broadcast({ type: 'logout' });
}
