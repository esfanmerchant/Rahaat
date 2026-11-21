import { useCallback, useEffect, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Pictogram } from '../../shared/components/Pictogram';
import { t, type Key } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { startActing, type Family } from '../actingControl';
import { sayKey } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { Keypad, PinDots } from '../Keypad';
import { PIN_MAX, PIN_MIN } from '../phone';

interface Refusal {
  key: Key;
  /** Tries left (shown as a number, so the helper knows how careful to be). */
  left?: number;
  /** Seconds until the lock ends. */
  wait?: number;
  reference?: string | undefined;
}

/** What the server's refusal means for the helper, in plain words. */
function refusalFor(failure: ApiFailure): Refusal {
  const problem = failure.problem as (ApiFailure['problem'] & { attempts_left?: number; retry_after?: number }) | undefined;
  const reference = problem?.request_id;
  switch (problem?.code) {
    case 'pin_incorrect':
      return { key: 'helper_pin_wrong', ...(typeof problem.attempts_left === 'number' ? { left: problem.attempts_left } : {}), reference };
    case 'pin_locked':
      return { key: 'helper_pin_locked', wait: typeof problem.retry_after === 'number' ? problem.retry_after : 60, reference };
    case 'pin_blocked':
      return { key: 'helper_pin_blocked', reference };
    case 'pin_not_set':
      return { key: 'helper_pin_none', reference };
    case 'no_delegation':
      return { key: 'helper_pin_nohelp', reference };
    default:
      if (failure.kind === 'offline') return { key: 'state_offline_body' };
      if (failure.kind === 'rate_limited') return { key: 'helper_pin_locked', wait: 60, reference };
      return { key: 'state_error_body', reference };
  }
}

/** Helper Mode, step two: this family's own PIN (never the helper's). PIN digits are never spoken. */
export function FamilyPin({ family, shownName, onBack }: { family: Family; shownName: string; onBack: () => void }) {
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const locked = until > now;

  // Count the lock down, so the keypad opens by itself.
  useEffect(() => {
    if (until <= Date.now()) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [until]);

  const onDigit = useCallback(
    (digit: string) => {
      if (!busy && !locked) setPin((value) => (value.length < PIN_MAX ? value + digit : value));
    },
    [busy, locked],
  );
  const onDelete = useCallback(() => {
    if (!busy) setPin((value) => value.slice(0, -1));
  }, [busy]);

  const onDone = useCallback(() => {
    if (pin.length < PIN_MIN || busy || locked) return;
    setBusy(true);
    setRefusal(null);
    void startActing(family, pin).then((result) => {
      // On success this screen is replaced by the family's home (acting is set).
      if (result.ok) return;
      setBusy(false);
      setPin('');
      const why = refusalFor(result.failure);
      setRefusal(why);
      if (why.wait) {
        setNow(Date.now());
        setUntil(Date.now() + why.wait * 1000);
      }
      sayKey(why.key);
    });
  }, [pin, busy, locked, family]);

  const minutes = refusal?.wait ? Math.max(1, Math.ceil((until - now) / 60000)) : 0;

  return (
    <CitizenShell onBack={busy ? undefined : onBack} prompt="helper_pin_hint">
      <div class="flex items-center gap-4">
        <Pictogram name="lock" size={56} class="text-primary" />
        <div class="flex min-w-0 flex-col">
          {/* The family's name is server data: text. */}
          <p class="text-xl font-bold" dir="auto">
            {shownName}
          </p>
          <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
            {t('helper_pin_title')}
          </h1>
        </div>
      </div>
      <p class="text-lg text-ink-muted">{t('helper_pin_hint')}</p>
      <PinDots count={pin.length} label={t('helper_pin_title')} />
      {refusal ? (
        <div role="alert" class="flex items-start gap-3 rounded-lg border-2 border-danger bg-danger-soft p-3 text-danger">
          <Pictogram name="warning" size={36} />
          <div class="flex flex-1 flex-col items-start gap-2">
            <p class="text-lg font-semibold">{t(refusal.key)}</p>
            {refusal.left !== undefined ? <p class="text-lg font-bold text-ink">{t('helper_pin_left', { count: refusal.left })}</p> : null}
            {locked ? <p class="text-lg font-bold text-ink">{t('helper_pin_wait', { minutes })}</p> : null}
            {refusal.reference ? <p class="text-sm text-ink">{t('state_reference', { id: refusal.reference })}</p> : null}
            <AudioPrompt prompt={refusal.key} />
          </div>
        </div>
      ) : null}
      <Keypad onDigit={onDigit} onDelete={onDelete} onDone={onDone} doneEnabled={pin.length >= PIN_MIN} disabled={busy || locked} busy={busy} />
    </CitizenShell>
  );
}
