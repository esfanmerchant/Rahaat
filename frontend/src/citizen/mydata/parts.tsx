import type { ComponentChildren } from 'preact';
import type { SpeechItem } from '../../shared/audio';
import type { ConsentOut, ConsentScope } from '../../shared/api/types';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { CrossedPictogram, Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { isMessageKey, lang, t, type Lang, type MessageKey } from '../../shared/i18n';
import { formatDate } from '../result/data';
import { ALL_SCOPES, effectiveStatus } from './api';

/** One picture per kind of data: identity is the card, contact the phone, and so on. */
export const SCOPE_ICON: Record<ConsentScope, PictogramName> = {
  identity: 'card',
  contact: 'phone',
  household: 'family',
  income: 'income-2',
  documents: 'document',
};

export function scopeKey(scope: string): MessageKey {
  const key = `mydata_scope_${scope}`;
  return isMessageKey(key) ? key : 'mydata_purpose_other';
}

export function purposeKey(purpose: string): MessageKey {
  const key = `mydata_purpose_${purpose}`;
  return isMessageKey(key) ? key : 'mydata_purpose_other';
}

export function knownScopes(consent: ConsentOut): ConsentScope[] {
  return ALL_SCOPES.filter((scope) => consent.field_scopes.includes(scope));
}

const STATUS: Record<'active' | 'withdrawn' | 'expired', { key: MessageKey; box: string; icon: PictogramName }> = {
  active: { key: 'mydata_status_active', box: 'border-primary bg-primary-soft text-primary-strong', icon: 'yes' },
  withdrawn: { key: 'mydata_status_withdrawn', box: 'border-line-strong bg-surface text-ink', icon: 'pause' },
  expired: { key: 'mydata_status_expired', box: 'border-line-strong bg-surface text-ink', icon: 'clock' },
};

/** The pictogram chips for the kinds of data, each with its word. Crossed out when not shared. */
export function ScopeChips({ scopes, crossed = false }: { scopes: readonly ConsentScope[]; crossed?: boolean }) {
  return (
    <ul class="grid grid-cols-2 gap-2">
      {scopes.map((scope) => (
        <li key={scope} class="flex min-h-tap items-center gap-2 rounded-md border-2 border-line bg-paper px-2 py-1">
          {crossed ? (
            <CrossedPictogram name={SCOPE_ICON[scope]} size={36} class="text-ink-muted" />
          ) : (
            <Pictogram name={SCOPE_ICON[scope]} size={36} class="text-primary-strong" />
          )}
          <span class="text-base font-semibold text-ink">{t(scopeKey(scope))}</span>
        </li>
      ))}
    </ul>
  );
}

/** What the speaker on a consent card says: who, what for, what they can see, until when. */
export function consentSpeech(consent: ConsentOut, code: Lang): { id: string; items: SpeechItem[]; lang: Lang } {
  const items: SpeechItem[] = [
    { key: 'mydata_holder', text: t('mydata_holder', undefined, code) },
    // The department's name has no recording: a device voice reads it where one exists.
    { key: 'holder.dynamic', text: consent.grantee_name },
    { key: purposeKey(consent.purpose), text: t(purposeKey(consent.purpose), undefined, code) },
    { key: 'mydata_what', text: t('mydata_what', undefined, code) },
  ];
  for (const scope of knownScopes(consent)) items.push({ key: scopeKey(scope), text: t(scopeKey(scope), undefined, code) });
  const status = STATUS[effectiveStatus(consent)];
  items.push({ key: status.key, text: t(status.key, undefined, code) });
  if (consent.expires_at && effectiveStatus(consent) === 'active') {
    items.push({ key: 'mydata_until', text: t('mydata_until', undefined, code) });
    items.push({ key: 'until.dynamic', text: formatDate(consent.expires_at, code) });
  }
  return { id: `consent:${consent.id}:${consent.version}:${consent.status}:${code}`, items, lang: code };
}

/** One consent: who has the data, for what, which kinds, until when, and its status. */
export function ConsentCard({ consent, children }: { consent: ConsentOut; children?: ComponentChildren }) {
  const code = lang.value;
  const status = effectiveStatus(consent);
  const spec = STATUS[status];
  return (
    <article class="flex flex-col gap-3 rounded-lg border-2 border-line-strong bg-paper p-3">
      <div class="flex items-start justify-between gap-2">
        <div class="flex min-w-0 flex-col">
          <span class="text-sm font-semibold text-ink-muted">{t('mydata_holder')}</span>
          {/* The department's name is server data: text, in its own direction. */}
          <h2 class="text-xl font-bold" dir="auto">
            <bdi>{consent.grantee_name}</bdi>
          </h2>
        </div>
        <AudioPrompt speech={consentSpeech(consent, code)} class="shrink-0" />
      </div>
      <p class="flex items-center gap-2 text-lg text-ink">
        <Pictogram name={consent.purpose === 'scam_report' ? 'shield' : 'payment'} size={32} class="text-primary" />
        <span class="flex-1">{t(purposeKey(consent.purpose))}</span>
      </p>
      <div class="flex flex-col gap-2">
        <span class="text-base font-semibold text-ink-muted">{t('mydata_what')}</span>
        <ScopeChips scopes={knownScopes(consent)} crossed={status !== 'active'} />
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class={`inline-flex items-center gap-1 rounded-full border-2 px-3 py-1 text-base font-semibold ${spec.box}`}>
          <Pictogram name={spec.icon} size={24} />
          {t(spec.key)}
        </span>
        {status === 'active' && consent.expires_at ? (
          <span class="inline-flex items-center gap-1 text-base text-ink-muted">
            <Pictogram name="clock" size={24} />
            {t('mydata_until')}: {formatDate(consent.expires_at, code)}
          </span>
        ) : null}
      </div>
      {children}
    </article>
  );
}

/**
 * RESERVED: "Who looked at my information" (the access log). Another track is
 * building its endpoint now; its shape is not known, so nothing is drawn or
 * fetched yet. When it lands, render the list here (each read: who, when, why)
 * and turn on ACCESS_LOG_READY. Until then the section stays hidden, so no
 * half-built screen is reachable.
 */
export const ACCESS_LOG_READY = false;

export function AccessLogSection() {
  if (!ACCESS_LOG_READY) return null;
  return null;
}
