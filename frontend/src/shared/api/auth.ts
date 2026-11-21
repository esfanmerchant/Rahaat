import { signal } from '@preact/signals';
import { hasChosenLang, isLang, setLang, type MessageKey } from '../i18n';
import { online } from '../network';
import { deletePref, getPref, setPref } from '../prefs';
import { anyVault, forgetVaultState, hasVault, lockReason, lockVault, openAfterLogin, openOffline, vaultState, wipeVault } from '../vault';
import { api } from './client';
import { call, type ApiFailure, type Result } from './problem';
import {
  applyAuth,
  applyLocal,
  broadcast,
  clearAuth,
  CSRF_HEADER,
  getAccessToken,
  isLocalSession,
  onSessionEnd,
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

/** A message for the sign-in screen after the app signed someone out (five wrong PINs). */
export const loginNotice = signal<MessageKey | null>(null);

const PERSON_ROLES: ReadonlySet<string> = new Set(['citizen', 'helper']);

/**
 * After the session is known: a citizen or helper with data sealed on this
 * phone must type the PIN first (the key never survives a reload).
 */
async function decideLock(): Promise<void> {
  const now = session.peek();
  if (now.status !== 'signed-in' || !PERSON_ROLES.has(now.active.role)) {
    if (vaultState.peek() === 'locked') forgetVaultState();
    return;
  }
  if (vaultState.peek() === 'open') return;
  if (await hasVault(now.user.id)) {
    vaultState.value = 'locked';
    lockReason.value ??= 'reload';
  } else {
    forgetVaultState();
  }
}

// The key never outlives the session in memory: sign-out, expiry or another person signing in drops it.
onSessionEnd(() => lockVault('reload'), { sessionOnly: true });

// A sign-in in another tab replaced the cookie: once this tab has the new session, decide on the lock again.
if (typeof BroadcastChannel !== 'undefined') {
  new BroadcastChannel('rahat-auth').addEventListener('message', (event: MessageEvent<{ type?: string }>) => {
    if (event.data?.type === 'login') void refreshSession().then(() => decideLock());
  });
}

/**
 * Call once at startup. Restores the session from the refresh cookie, so a
 * reload keeps the person signed in without storing any token in the browser.
 */
export async function restoreSession(): Promise<void> {
  session.value = { status: 'restoring' };
  // Lock first when this phone holds sealed data, so no screen shows before the PIN.
  if (vaultState.peek() !== 'open' && (await anyVault())) {
    vaultState.value = 'locked';
    lockReason.value = 'reload';
  }

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
    await decideLock();
    return;
  }
  // No cookie on a first visit is not an "expired" session.
  if (outcome === 'offline') clearAuth('offline');
  else if (outcome === 'error') clearAuth('error');
  else clearAuth('none');
}

// Network back: retry a restore that failed for lack of one, and turn an
// offline sign-in into a real session (the cookie, or the sign-in screen).
online.subscribe((isOnline) => {
  if (!isOnline) return;
  const now = session.peek();
  if (now.status === 'signed-out' && now.reason === 'offline') void restoreSession();
  else if (isLocalSession()) void refreshSession();
});

export type LoginResult = { ok: true; role: Role; offline: boolean } | { ok: false; failure: ApiFailure };

/**
 * Sign in with phone and PIN. Online, the server checks them and the PIN opens
 * (or starts) this person's sealed data on the phone. With no network, the
 * PIN can open that data instead, so saved answers can be seen and added to.
 */
export async function login(body: LoginBody): Promise<LoginResult> {
  const result: Result<AuthOut> = await call(api.POST('/v1/auth/login', { body }));
  if (!result.ok) {
    const kind = result.failure.kind;
    if (kind !== 'offline' && kind !== 'network') return result;
    const local = await openOffline(body.identifier, body.secret);
    if (local === 'wrong') return { ok: false, failure: { kind: 'unauthenticated' } };
    if (local === 'none') return result;
    applyLocal(local.user, local.active, local.memberships);
    adoptProfileLanguage(local.user, local.active.role);
    loginNotice.value = null;
    return { ok: true, role: local.active.role, offline: true };
  }
  void deletePref('pendingLogout'); // a fresh login supersedes an unfinished logout
  applyAuth(result.data);
  adoptProfileLanguage(result.data.user, result.data.active.role);
  loginNotice.value = null;
  broadcast({ type: 'login' });
  if (PERSON_ROLES.has(result.data.active.role)) await openAfterLogin(body.identifier, body.secret, result.data);
  else forgetVaultState();
  return { ok: true, role: result.data.active.role, offline: false };
}

export async function switchTenant(tenantId: string, role?: Role): Promise<Result<AuthOut>> {
  const body = role === undefined ? { tenant_id: tenantId } : { tenant_id: tenantId, role };
  const result = await call(api.POST('/v1/auth/switch', { body }));
  if (result.ok) applyAuth(result.data);
  return result;
}

async function serverLogout(token: string | null = getAccessToken()): Promise<boolean> {
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
 * The person's sealed data on the phone is deleted too, unless `keepVault`
 * (someone else picked up the phone: the owner's unsent answers stay sealed).
 */
export async function logout(options: { keepVault?: boolean } = {}): Promise<void> {
  const now = session.peek();
  const token = getAccessToken();
  // Memory and screens first, so nothing of the person shows while the server is asked.
  clearAuth('logout');
  broadcast({ type: 'logout' });
  // Noted before the server call: if the app closes now, the next start finishes the logout.
  await setPref('pendingLogout', true);
  if (now.status === 'signed-in' && !options.keepVault) await wipeVault(now.user.id);
  if (await serverLogout(token)) await deletePref('pendingLogout');
}
