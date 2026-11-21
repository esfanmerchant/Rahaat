import { signal } from '@preact/signals';
import { acting } from '../shared/acting';
import { onSessionEnd } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import type { ApplicationStatus, ApplicationSummary } from '../shared/api/types';

/**
 * The status of the person's latest application, kept in memory for the left pane of the laptop layout
 * (the journey stars stay in place across routes). Only an enum, never the application itself.
 * `undefined`: not asked yet. `null`: no application. Wiped on every sign-out and every Helper Mode switch.
 */
export const journeyStatus = signal<ApplicationStatus | null | undefined>(undefined);

let loading = false;
let epochKey = '';

function reset(): void {
  journeyStatus.value = undefined;
  loading = false;
}

onSessionEnd(reset);
// A helper switching families must never see the previous family's journey.
acting.subscribe((now) => {
  const key = now?.personId ?? '';
  if (key !== epochKey) {
    epochKey = key;
    reset();
  }
});

/** The status that matters: the latest application that is not a withdrawn one. */
export function latestStatus(items: readonly ApplicationSummary[]): ApplicationStatus | null {
  const byNewest = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return (byNewest.find((item) => item.status !== 'withdrawn') ?? null)?.status ?? null;
}

export function setJourney(items: readonly ApplicationSummary[]): void {
  journeyStatus.value = latestStatus(items);
}

/** Load once when no screen has told us yet (a deep link to /scam, a reload on /track). */
export async function ensureJourney(): Promise<void> {
  if (loading || journeyStatus.peek() !== undefined) return;
  loading = true;
  const result = await call(api.GET('/v1/applications'));
  loading = false;
  if (result.ok && journeyStatus.peek() === undefined) setJourney(result.data.items);
}
