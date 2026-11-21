import { signal } from '@preact/signals';
import { onSessionEnd } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import type { ConsentOut, ConsentScope } from '../../shared/api/types';
import type { MessageKey } from '../../shared/i18n';
import { newId } from '../../shared/ids';
import { resetFlow } from '../apply/flow';

/** The person's consents as last read from the server (memory only). */
export const consents = signal<ConsentOut[] | null>(null);
/** What the list says once after a change ("Done. You share less now."). */
export const doneNotice = signal<MessageKey | null>(null);

onSessionEnd(() => {
  consents.value = null;
  doneNotice.value = null;
});

export const ALL_SCOPES: readonly ConsentScope[] = ['identity', 'contact', 'household', 'income', 'documents'];

export function effectiveStatus(consent: ConsentOut): 'active' | 'withdrawn' | 'expired' {
  if (consent.status === 'withdrawn') return 'withdrawn';
  if (consent.status === 'expired') return 'expired';
  if (consent.expires_at && new Date(consent.expires_at).getTime() <= Date.now()) return 'expired';
  return consent.status === 'active' ? 'active' : 'expired';
}

export async function loadConsents(): Promise<Result<ConsentOut[]>> {
  const result = await call(api.GET('/v1/consents'));
  if (result.ok) consents.value = result.data;
  return result;
}

function replace(updated: ConsentOut): void {
  const list = consents.peek() ?? [];
  const exists = list.some((item) => item.id === updated.id);
  consents.value = exists ? list.map((item) => (item.id === updated.id ? updated : item)) : [updated, ...list];
}

/** Share less: the server only allows removing kinds of data, never adding them. */
export async function narrowConsent(id: string, keep: readonly ConsentScope[]): Promise<Result<ConsentOut>> {
  const result = await call(
    api.PATCH('/v1/consents/{consent_id}', { params: { path: { consent_id: id } }, body: { field_scopes: [...keep] } }),
  );
  if (result.ok) {
    replace(result.data);
    resetFlow(); // the open application is read again from the server with what may still be written
  }
  return result;
}

/** Take it back: applications pause and officers lose access on the next request. */
export async function withdrawConsent(id: string): Promise<Result<ConsentOut>> {
  const result = await call(api.POST('/v1/consents/{consent_id}/withdraw', { params: { path: { consent_id: id } } }));
  if (result.ok) {
    replace(result.data);
    resetFlow();
  }
  return result;
}

let grantKey: string | null = null;

/** Share again, with the kinds of data shared before. Paused applications carry on. */
export async function shareAgain(previous: ConsentOut): Promise<Result<ConsentOut>> {
  grantKey ??= newId();
  const scopes = ALL_SCOPES.filter((scope) => previous.field_scopes.includes(scope));
  const result = await call(
    api.POST('/v1/consents', {
      body: { purpose: previous.purpose, field_scopes: scopes.length > 0 ? scopes : [...ALL_SCOPES], expires_in_days: 180 },
      headers: { 'Idempotency-Key': grantKey },
    }),
  );
  if (result.ok) {
    grantKey = null;
    replace(result.data);
    resetFlow();
  }
  return result;
}
