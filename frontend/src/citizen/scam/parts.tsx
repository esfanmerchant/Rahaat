import { useEffect } from 'preact/hooks';
import { buzz, celebrate, chime } from '../../shared/feedback';
import type { ScamCertainty, ScamCheckOut, ScamReview, ScamUrl } from '../../shared/api/types';
import { CrossedPictogram, Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { dirOf, isLang, lang, t, type Lang, type MessageKey } from '../../shared/i18n';
import { formatDate } from '../result/data';

type Tone = 'danger' | 'warn' | 'check' | 'ok';

/** One picture, colour and short name per answer. The picture differs too, so colour is never the only sign. */
export const CERTAINTY: Record<ScamCertainty, { icon: PictogramName; tone: Tone; key: MessageKey }> = {
  likely_scam: { icon: 'msg-scam', tone: 'danger', key: 'scam_certainty_likely_scam' },
  might_be_scam: { icon: 'msg-warn', tone: 'warn', key: 'scam_certainty_might_be_scam' },
  not_sure: { icon: 'msg-unsure', tone: 'check', key: 'scam_certainty_not_sure' },
  looks_real: { icon: 'msg-ok', tone: 'ok', key: 'scam_certainty_looks_real' },
  confirmed_real: { icon: 'shield-ok', tone: 'ok', key: 'scam_certainty_confirmed_real' },
};

export function certaintyOf(value: string): (typeof CERTAINTY)[ScamCertainty] {
  return CERTAINTY[value as ScamCertainty] ?? CERTAINTY.not_sure;
}

export const TONE_BOX: Record<Tone, string> = {
  danger: 'border-danger bg-danger-soft text-danger',
  warn: 'border-warning bg-warning-soft text-warning-ink',
  check: 'border-info bg-info-soft text-info-strong',
  ok: 'border-primary bg-primary-soft text-primary-strong',
};

export const isScamWarning = (certainty: string): boolean => certainty === 'likely_scam' || certainty === 'might_be_scam';

/** The language a server answer was written in. */
export function answerLang(answer: ScamCheckOut): Lang {
  return isLang(answer.lang) ? answer.lang : lang.value;
}

/** A picture per reason code; links share one. Unknown codes get the warning sign. */
const REASON_ICON: Readonly<Record<string, PictogramName>> = {
  verify_code_confirmed: 'shield-ok',
  compare_with_app: 'phone',
  verify_code_not_found: 'warning',
  code_typo_possible: 'edit',
  code_real_text_changed: 'edit',
  code_real_text_differs: 'edit',
  asks_fee: 'payment',
  asks_money: 'payment',
  pay_to_receive: 'payment',
  asks_pin: 'lock',
  asks_otp: 'lock',
  asks_cnic: 'card',
  prize: 'star',
  urgency: 'clock',
  has_link: 'link',
  sender_lookalike: 'person',
  sender_mobile_official: 'phone',
  contact_number: 'phone',
  reads_like_scam: 'msg-warn',
  too_short: 'message',
  mixed_signals: 'unknown',
  model_unsure: 'unknown',
  no_scam_signs: 'yes',
  matches_template: 'yes',
  official_sender: 'yes',
  no_code_to_check: 'unknown',
  rahat_without_code: 'warning',
};

export function reasonIcon(code: string): PictogramName {
  if (code.startsWith('link_')) return 'link';
  return REASON_ICON[code] ?? 'warning';
}

const VERDICT_CARD: Record<Tone, string> = {
  danger: 'bg-danger text-white shadow-glow-madder',
  warn: 'bg-warning text-night shadow-lift',
  check: 'bg-info text-white shadow-lift',
  ok: 'bg-primary text-white shadow-glow-emerald',
};

/**
 * The big answer: a solid card in the verdict's colour (madder for a scam, saffron for a warning, indigo for
 * "not sure", emerald for a message that is really from Rahat), the picture popping into a ring, the server's
 * headline in its own language. A bell and a short buzz say it too (feedback.ts).
 */
export function AnswerHeader({ answer, headingRef }: { answer: ScamCheckOut; headingRef: { current: HTMLHeadingElement | null } }) {
  const spec = certaintyOf(answer.certainty);
  const code = answerLang(answer);
  useEffect(() => {
    const id = window.setTimeout(() => {
      if (spec.tone === 'ok') celebrate();
      else if (spec.tone === 'danger') {
        chime('warn');
        buzz([70, 50, 70]);
      } else chime(spec.tone === 'warn' ? 'warn' : 'soft');
    }, 450);
    return () => window.clearTimeout(id);
  }, [answer.report_id, spec.tone]);
  return (
    <div class={`relative flex flex-col items-center gap-3 overflow-hidden rounded-2xl px-4 py-6 text-center motion-safe:animate-rise ${VERDICT_CARD[spec.tone]}`}>
      <div aria-hidden="true" class="rh-lattice-night absolute inset-0 opacity-60" />
      <span class="relative grid size-36 place-items-center">
        {spec.tone === 'danger' ? <span aria-hidden="true" class="absolute size-32 rounded-full border-2 border-white/70 motion-safe:animate-ring" /> : null}
        <span class="grid size-36 place-items-center rounded-full bg-white/15 motion-safe:animate-pop" style={{ animationDelay: '150ms' }}>
          <Pictogram name={spec.icon} size={96} />
        </span>
      </span>
      <p class="relative rounded-full border-2 border-current px-4 py-1 text-lg font-bold">{t(spec.key)}</p>
      <h1 ref={headingRef} tabIndex={-1} lang={code} dir={dirOf(code)} class="relative text-2xl font-extrabold">
        {answer.headline}
      </h1>
    </div>
  );
}

export function Reasons({ answer }: { answer: ScamCheckOut }) {
  if (answer.reasons.length === 0) return null;
  const code = answerLang(answer);
  return (
    <section aria-labelledby="scam-reasons" class="flex flex-col gap-2">
      <h2 id="scam-reasons" class="text-lg font-semibold text-ink-muted">
        {t('scam_reasons')}
      </h2>
      <ul class="flex flex-col gap-2" lang={code} dir={dirOf(code)}>
        {answer.reasons.map((reason) => (
          <li key={reason.code} class="flex items-start gap-3 rounded-lg border-2 border-line bg-surface p-3">
            <Pictogram name={reasonIcon(reason.code)} size={40} class="text-ink" />
            {/* Server text, shown as text (never HTML). */}
            <p class="flex-1 text-lg text-ink">{reason.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const DONTS: ReadonlyArray<{ icon: PictogramName; key: MessageKey }> = [
  { icon: 'phone', key: 'scam_dont_call' },
  { icon: 'payment', key: 'scam_dont_pay' },
  { icon: 'lock', key: 'scam_dont_pin' },
];

/** What to do now: the server's sentence, and for a scam three "do not" pictures anyone can follow. */
export function WhatToDo({ answer }: { answer: ScamCheckOut }) {
  const code = answerLang(answer);
  const scam = isScamWarning(answer.certainty);
  return (
    <section aria-labelledby="scam-todo" class={`flex flex-col gap-3 rounded-lg border-2 p-3 ${scam ? 'border-danger' : 'border-line-strong'}`}>
      <h2 id="scam-todo" class="text-lg font-semibold text-ink-muted">
        {t('scam_what_to_do')}
      </h2>
      {scam ? (
        <ul class="grid grid-cols-3 gap-2">
          {DONTS.map((item) => (
            <li key={item.key} class="flex flex-col items-center gap-1 text-center">
              <CrossedPictogram name={item.icon} size={56} class="text-ink" />
              <span class="text-base font-semibold text-ink">{t(item.key)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p class="text-xl font-semibold text-ink" lang={code} dir={dirOf(code)}>
        {answer.what_to_do}
      </p>
    </section>
  );
}

const RISK: Record<ScamUrl['risk'], { key: MessageKey; box: string; icon: PictogramName }> = {
  high: { key: 'scam_risk_high', box: 'border-danger bg-danger-soft text-danger', icon: 'warning' },
  medium: { key: 'scam_risk_medium', box: 'border-warning bg-warning-soft text-warning-ink', icon: 'warning' },
  low: { key: 'scam_risk_low', box: 'border-line-strong bg-surface text-ink', icon: 'link' },
};

/**
 * Links found in the message, as plain text, never as links: the server has
 * already defanged them (hxxps://site[.]com), and nothing here is clickable.
 */
export function Links({ answer }: { answer: ScamCheckOut }) {
  if (answer.urls.length === 0) return null;
  const code = answerLang(answer);
  const risky = answer.urls.some((url) => url.risk !== 'low');
  return (
    <section aria-labelledby="scam-links" class="flex flex-col gap-2">
      <h2 id="scam-links" class="text-lg font-semibold text-ink-muted">
        {t('scam_links')}
      </h2>
      {risky ? <p class="text-base font-semibold text-danger">{t('scam_links_note')}</p> : null}
      <ul class="flex flex-col gap-2">
        {answer.urls.map((url, index) => {
          const risk = RISK[url.risk] ?? RISK.low;
          return (
            <li key={`${url.url}-${index}`} class={`flex flex-col gap-2 rounded-lg border-2 p-3 ${risk.box}`}>
              <p class="flex items-center gap-2 text-base font-bold">
                <Pictogram name={risk.icon} size={28} />
                {t(risk.key)}
              </p>
              <p dir="ltr" lang="en" class="rh-ltr select-text break-all rounded-md bg-paper px-2 py-1 font-mono text-base text-ink">
                {url.url}
              </p>
              {url.flag_texts.length > 0 ? (
                <ul class="flex flex-col gap-1 ps-1" lang={code} dir={dirOf(code)}>
                  {url.flag_texts.map((text) => (
                    <li key={text} class="text-base text-ink">
                      {text}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** confirmed_real: who really sent it and when. */
export function Verified({ answer }: { answer: ScamCheckOut }) {
  const verified = answer.verified;
  if (answer.certainty !== 'confirmed_real' || !verified?.genuine) return null;
  const ui = lang.value;
  return (
    <section aria-labelledby="scam-real" class="flex flex-col gap-3 rounded-lg border-4 border-primary bg-primary-soft p-4 text-primary-strong">
      <h2 id="scam-real" class="flex items-center gap-3 text-xl font-bold">
        <Pictogram name="shield-ok" size={48} />
        {t('scam_real_title')}
      </h2>
      <dl class="flex flex-col gap-2 text-ink">
        {verified.department ? (
          <div class="flex flex-col">
            <dt class="text-base font-semibold text-ink-muted">{t('scam_real_from')}</dt>
            <dd class="text-lg font-semibold">
              <bdi>{verified.department}</bdi>
            </dd>
          </div>
        ) : null}
        {verified.sent_at ? (
          <div class="flex flex-col">
            <dt class="text-base font-semibold text-ink-muted">{t('scam_real_when')}</dt>
            <dd class="text-lg font-semibold">{formatDate(verified.sent_at, ui)}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

const SCAM_LABELS = new Set(['relief_scam', 'phishing_link', 'advance_fee', 'impersonation']);

/** What a person decided, or that a person is still checking. */
export function reviewKey(review: ScamReview): MessageKey | null {
  if (review.status === 'waiting') return 'scam_review_waiting';
  if (review.status !== 'done') return null;
  if (review.confirmed_label && SCAM_LABELS.has(review.confirmed_label)) return 'scam_review_scam';
  if (review.confirmed_label === 'legit_program_message') return 'scam_review_real';
  return 'scam_review_other';
}

export function ReviewLine({ review }: { review: ScamReview }) {
  const key = reviewKey(review);
  if (!key) return null;
  const waiting = review.status === 'waiting';
  return (
    <p role="status" class={`flex items-center gap-3 rounded-lg border-2 p-3 text-lg font-semibold ${waiting ? TONE_BOX.check : 'border-ink bg-surface text-ink'}`}>
      <Pictogram name={waiting ? 'clock' : 'person-help'} size={40} />
      <span class="flex-1">{t(key)}</span>
    </p>
  );
}
