import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { ApiFailure } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { t, type MessageKey } from '../../shared/i18n';
import { go } from '../../shared/routing';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { CitizenShell } from '../CitizenShell';
import { consentNeeded, draft, firstOpenStep, giveConsent, stepPath } from './flow';
import { InlineFailure, Notice, sayKey, StepLayout } from './parts';

const ROWS: ReadonlyArray<{ icon: PictogramName; label: MessageKey; body: MessageKey }> = [
  { icon: 'person', label: 'consent_what_label', body: 'consent_what' },
  { icon: 'payment', label: 'consent_why_label', body: 'consent_why' },
  { icon: 'retry', label: 'consent_takeback_label', body: 'consent_takeback' },
];

/** a. Consent: what we use, for what, and that it can be taken back. Yes or No. */
export function ConsentStep() {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const needed = consentNeeded.value;

  const agree = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await giveConsent();
    setBusy(false);
    if (!result.ok) {
      // One open application per program: the person already has one, so show it.
      if (result.failure.kind === 'conflict' && result.failure.problem?.code === 'application_exists') {
        route('/track');
        return;
      }
      setFailure(result.failure);
      return;
    }
    // Back to the first question still open: the card for a new application,
    // or where the person was when the server asked for consent again. Offline
    // the consent waits on the phone and is sent first when the network is back.
    if (result.data.queued) sayKey('outbox_stored');
    const d = draft.peek();
    go(route, stepPath(d ? firstOpenStep(d) : 'card'));
  };

  return (
    <StepLayout step="consent" prompt="consent_prompt" icon="lock" title={t('consent_title')} busy={busy}>
      {needed ? <Notice tone="warn" icon="lock" text={t('apply_need_consent')} /> : null}
      <ul class="flex flex-col gap-3">
        {ROWS.map((row) => (
          <li key={row.body} class="flex items-start gap-3 rounded-xl border-2 border-line bg-surface p-3 lg:gap-4 lg:p-4">
            <Pictogram name={row.icon} size={48} class="text-primary" />
            <div class="flex flex-col">
              <span class="text-base font-semibold text-ink-muted">{t(row.label)}</span>
              <span class="text-lg text-ink">{t(row.body)}</span>
            </div>
          </li>
        ))}
      </ul>
      {failure ? <InlineFailure failure={failure} /> : null}
      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" icon="yes" block busy={busy} onClick={() => void agree()}>
          {t('consent_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block disabled={busy} onClick={() => route('/apply/declined')}>
          {t('consent_no')}
        </Button>
      </div>
    </StepLayout>
  );
}

/** No on the consent screen ends the flow kindly. */
export function ConsentDeclined() {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  return (
    <CitizenShell onBack={() => route('/apply/consent')} prompt="consent_no_body">
      <div class="flex flex-1 flex-col items-center gap-5 py-6 text-center">
        <Pictogram name="home" size={96} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('consent_no_title')}
        </h1>
        <p class="text-lg text-ink-muted">{t('consent_no_body')}</p>
      </div>
      <Button size="lg" icon="home" block onClick={() => route('/')}>
        {t('go_home')}
      </Button>
    </CitizenShell>
  );
}
