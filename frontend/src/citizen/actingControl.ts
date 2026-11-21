import { signal } from '@preact/signals';
import { acting, setActing, type Acting } from '../shared/acting';
import { api } from '../shared/api/client';
import { call, type Result } from '../shared/api/problem';
import { wipePerson } from '../shared/api/session';
import type { SwitchOut } from '../shared/api/types';
import { stopAudio } from '../shared/audio';
import { persistNow, restoreSealed } from './apply/outbox';

/**
 * Helper Mode on a shared phone. Switching to a family, handing the phone
 * back and three minutes without a tap all do the same: seal what the family
 * has not sent (under that family's own name), wipe everything of theirs from
 * memory, and tell the server to stop the ticket.
 */
export const ACTING_IDLE_MS = 3 * 60 * 1000;

/** Why the phone was handed back, shown once on the family list. */
export const handedBack = signal<'idle' | 'expired' | null>(null);

let lastTap = Date.now();

export interface Family {
  personId: string;
  name: string;
  nameUr: string | null;
}

/** Check the family PIN; on success this family is in front of the helper and nobody else's data is in memory. */
export async function startActing(family: Family, pin: string): Promise<Result<SwitchOut>> {
  const result = await call(api.POST('/v1/helper/switch', { body: { person_id: family.personId, pin } }));
  if (!result.ok) return result;
  wipePerson();
  handedBack.value = null;
  lastTap = Date.now();
  const next: Acting = {
    personId: family.personId,
    name: result.data.display_name ?? family.name,
    nameUr: family.nameUr,
    scopes: result.data.scopes,
    ticket: result.data.ticket,
    expiresAt: Date.now() + result.data.expires_in * 1000,
  };
  setActing(next);
  void restoreSealed(); // this family's own unsent answers, never another's
  return result;
}

let ending: Promise<void> | null = null;

/** Hand the phone back. Safe to call twice. */
export function endActing(reason: 'done' | 'idle' | 'expired' = 'done'): Promise<void> {
  if (!acting.peek()) return Promise.resolve();
  ending ??= (async () => {
    try {
      await persistNow(); // unsent answers stay sealed under this family's name
    } catch {
      // sealing is best effort; the wipe must still happen
    }
    stopAudio();
    setActing(null);
    wipePerson();
    if (reason !== 'done') handedBack.value = reason;
    // The server stops the ticket too (the helper's own session, no family headers). Offline, the ticket dies by itself.
    await call(api.POST('/v1/helper/switch/end'));
  })().finally(() => {
    ending = null;
  });
  return ending;
}

if (typeof document !== 'undefined') {
  const touch = (): void => {
    lastTap = Date.now();
  };
  for (const name of ['pointerdown', 'keydown', 'touchstart'] as const) {
    document.addEventListener(name, touch, { capture: true, passive: true });
  }
  const check = (): void => {
    const now = acting.peek();
    if (!now) return;
    if (Date.now() >= now.expiresAt) void endActing('expired');
    else if (Date.now() - lastTap >= ACTING_IDLE_MS) void endActing('idle');
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check();
  });
  setInterval(check, 5000);
}
