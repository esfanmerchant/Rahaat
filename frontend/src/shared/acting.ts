import { signal } from '@preact/signals';
import { onSessionEnd } from './api/session';

/**
 * Helper Mode: the family a helper is acting for on a shared phone. Memory
 * only. While set, every API request carries `X-Acting-For` and
 * `X-Helper-Ticket`; the banner shows who it is on every screen.
 */
export interface Acting {
  personId: string;
  /** The name to show, in the person's own words where we have them. */
  name: string;
  nameUr: string | null;
  scopes: readonly string[];
  ticket: string;
  /** When the server stops honouring the ticket (ms since epoch). */
  expiresAt: number;
}

export const acting = signal<Acting | null>(null);

let epoch = 0;

/** Changes on every switch and every end: an answer that arrives for an earlier one is thrown away. */
export function actingEpoch(): number {
  return epoch;
}

export function setActing(next: Acting | null): void {
  epoch += 1;
  acting.value = next;
}

/** The request headers for the family in front of the helper, or null. */
export function actingHeaders(): Record<string, string> | null {
  const now = acting.peek();
  return now ? { 'X-Acting-For': now.personId, 'X-Helper-Ticket': now.ticket } : null;
}

/** Name for the sealed queue of this family (separate from every other family's). */
export function actingScope(): string | null {
  return acting.peek()?.personId ?? null;
}

onSessionEnd(() => setActing(null));
