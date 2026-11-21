import { logout } from './api/auth';
import { dropAccessToken, session, wipeMemory } from './api/session';
import { stopAudio } from './audio';
import { lockVault, vaultState } from './vault';

/**
 * Lock after idle: when nobody touched the app for IDLE_MS, the key and
 * everything decrypted are wiped from memory and the PIN is asked again. The
 * sealed outbox stays, so unsent answers are not lost. Without a vault (the
 * browser cannot encrypt) there is nothing a PIN could open: the app signs out.
 */
export const IDLE_MS = 10 * 60 * 1000;
const CHECK_MS = 15 * 1000;
const PERSON_ROLES: ReadonlySet<string> = new Set(['citizen', 'helper']);

let lastActive = Date.now();
const beforeLockHooks = new Set<() => Promise<void>>();

/** Run before the lock (the outbox seals what is still in memory). */
export function beforeLock(hook: () => Promise<void>): () => void {
  beforeLockHooks.add(hook);
  return () => beforeLockHooks.delete(hook);
}

export async function lockNow(reason: 'idle' | 'reload' = 'idle'): Promise<void> {
  for (const hook of beforeLockHooks) {
    try {
      await hook();
    } catch {
      // sealing is best effort; the lock must still happen
    }
  }
  stopAudio();
  if (vaultState.peek() === 'open') {
    lockVault(reason);
    wipeMemory();
    dropAccessToken();
  } else {
    await logout({ keepVault: true });
  }
}

function check(): void {
  const now = session.peek();
  if (now.status !== 'signed-in' || !PERSON_ROLES.has(now.active.role) || vaultState.peek() === 'locked') {
    lastActive = Date.now();
    return;
  }
  if (Date.now() - lastActive >= IDLE_MS) void lockNow('idle');
}

if (typeof document !== 'undefined') {
  const touch = (): void => {
    lastActive = Date.now();
  };
  for (const name of ['pointerdown', 'keydown', 'touchstart'] as const) {
    document.addEventListener(name, touch, { capture: true, passive: true });
  }
  // A phone put away: check as soon as it is looked at again.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check();
  });
  setInterval(check, CHECK_MS);
}
