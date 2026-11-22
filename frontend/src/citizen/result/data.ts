import { signal } from '@preact/signals';
import { useEffect, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call, type ApiFailure, type Result } from '../../shared/api/problem';
import type { ApplicationOut, ApplicationStatus, ApplicationSummary } from '../../shared/api/types';
import type { PictogramName } from '../../shared/components/Pictogram';
import { messageKeyFor, type Lang, type MessageKey } from '../../shared/i18n';
import { lastSubmit } from '../apply/flow';

/** True while an appeal star is the current step on the tracker, so the star before it is not gold too. */
export const appealNow = signal(false);

export type Loaded =
  | { state: 'loading' }
  | { state: 'failed'; failure: ApiFailure }
  | { state: 'empty' }
  | { state: 'ready'; app: ApplicationOut };

/** The application to show: the one just submitted, else the latest that is not a draft. */
async function loadLatest(): Promise<Result<ApplicationOut | null>> {
  const list = await call(api.GET('/v1/applications'));
  if (!list.ok) return list;
  const byNewest = (a: ApplicationSummary, b: ApplicationSummary): number => b.updated_at.localeCompare(a.updated_at);
  const items = [...list.data.items].sort(byNewest);
  const chosen = items.find((item) => item.status !== 'draft' && item.status !== 'withdrawn') ?? items[0];
  if (!chosen) return { ok: true, data: null };
  return call(api.GET('/v1/applications/{application_id}', { params: { path: { application_id: chosen.id } } }));
}

/**
 * Load the application for the result, tracker, ask-a-person and proof
 * screens. `fresh: false` uses the submit response when there is one (the
 * result screen right after Send); the tracker always reads the server.
 */
export function useApplication(fresh: boolean): { loaded: Loaded; reload: () => void } {
  const recent = lastSubmit.value;
  const [loaded, setLoaded] = useState<Loaded>(
    !fresh && recent ? { state: 'ready', app: recent.application } : { state: 'loading' },
  );
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!fresh && recent && attempt === 0) return undefined;
    let live = true;
    setLoaded({ state: 'loading' });
    void loadLatest().then((result) => {
      if (!live) return;
      if (!result.ok) setLoaded({ state: 'failed', failure: result.failure });
      else setLoaded(result.data ? { state: 'ready', app: result.data } : { state: 'empty' });
    });
    return () => {
      live = false;
    };
  }, [attempt]);
  return { loaded, reload: () => setAttempt((n) => n + 1) };
}

export const STATUS_ICON: Record<ApplicationStatus, PictogramName> = {
  draft: 'document',
  submitted: 'document',
  needs_proof: 'document',
  in_review: 'person-help',
  approved: 'yes',
  rejected: 'no',
  paid: 'payment',
  on_hold_consent: 'lock',
  withdrawn: 'no',
};

export function statusKey(status: string): MessageKey {
  return messageKeyFor(`status_${status}`) ?? 'status_submitted';
}

export function statusIcon(status: string): PictogramName {
  return STATUS_ICON[status as ApplicationStatus] ?? 'clock';
}

/** A date (and with `withTime`, the time) in the person's language, with 0-9 digits as everywhere else in the app. */
export function formatDate(iso: string, code: Lang, withTime = false): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(code === 'ur' ? 'ur-PK-u-nu-latn' : 'en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date);
}
