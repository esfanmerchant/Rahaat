import { useCallback, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { playPrompt } from '../shared/audio';
import { login, loginNotice } from '../shared/api/auth';
import { demoMode } from '../shared/api/system';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Pictogram } from '../shared/components/Pictogram';
import { lang, t, type MessageKey } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { vaultState } from '../shared/vault';
import { CitizenShell } from './CitizenShell';
import { Keypad, PinDots } from './Keypad';
import { PhoneSlots, usePhonePaste } from './PhoneField';
import { checkPhone, formatPhone, isValidPin, mockPhone, PHONE_LENGTH, PIN_MAX, PIN_MIN } from './phone';

type Step = 'phone' | 'pin';

const DIGIT_KEYS = [
  'digit_0',
  'digit_1',
  'digit_2',
  'digit_3',
  'digit_4',
  'digit_5',
  'digit_6',
  'digit_7',
  'digit_8',
  'digit_9',
] as const satisfies readonly MessageKey[];

interface Notice {
  key: MessageKey;
  requestId?: string | undefined;
}

/**
 * Citizen sign-in: step 1 the mock phone number, step 2 the PIN, each on its
 * own screen with the big keypad. Digits of the phone number are spoken; PIN
 * digits are never spoken (someone nearby could hear them).
 */
export function LoginScreen() {
  const { route } = useLocation();
  const [step, setStep] = useState<Step>('phone');
  const [local, setLocal] = useState('');
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(() => (loginNotice.peek() ? { key: loginNotice.peek() as MessageKey } : null));
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const code = lang.value;

  // A short buzz confirms each key press (Android; iOS has no vibrate).
  const tap = (): void => {
    if (typeof navigator === 'undefined' || !('vibrate' in navigator)) return;
    if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return;
    navigator.vibrate(10);
  };

  const onDigit = useCallback(
    (digit: string) => {
      if (busy) return;
      setNotice(null);
      tap();
      if (step === 'phone') {
        setLocal((value) => (value.length < PHONE_LENGTH ? value + digit : value));
        const key = DIGIT_KEYS[Number(digit)];
        if (key) playPrompt(key, code, t(key, undefined, code));
      } else {
        setPin((value) => (value.length < PIN_MAX ? value + digit : value));
      }
    },
    [busy, step, code],
  );

  usePhonePaste(
    useCallback((digits: string) => {
      setNotice(null);
      setLocal(digits);
    }, []),
    step === 'phone' && !busy,
  );

  const onDelete = useCallback(() => {
    if (busy) return;
    setNotice(null);
    tap();
    if (step === 'phone') setLocal((value) => value.slice(0, -1));
    else setPin((value) => value.slice(0, -1));
  }, [busy, step]);

  const show = (key: MessageKey, requestId?: string): void => {
    setNotice({ key, requestId });
    playPrompt(key, code, t(key, undefined, code));
  };

  const submit = async (): Promise<void> => {
    if (!isValidPin(pin)) {
      show('login_pin_too_short');
      return;
    }
    // Offline the server cannot be asked, but the PIN may open this person's
    // answers saved on the phone (login() tries that); otherwise "no internet".
    setBusy(true);
    setNotice(null);
    const result = await login({ identifier: mockPhone(local), secret: pin });
    setBusy(false);
    if (result.ok) return; // the /login route guard sends the person to their home
    setPin('');
    switch (result.failure.kind) {
      case 'unauthenticated':
      case 'validation':
      case 'not_found':
        show('login_wrong');
        break;
      case 'locked':
      case 'rate_limited':
        show('login_locked');
        break;
      case 'offline':
        show('state_offline_body');
        break;
      default:
        show('state_error_body', result.failure.problem?.request_id);
    }
  };

  const onDone = useCallback(() => {
    if (step === 'phone') {
      const check = checkPhone(local);
      if (check !== 'ok') {
        show(check === 'not_mock' ? 'phone_not_mock' : 'login_phone_invalid');
        return;
      }
      setNotice(null);
      setStep('pin');
      playPrompt('login_pin_hint', code, t('login_pin_hint', undefined, code));
      return;
    }
    void submit();
  }, [step, local, pin, code]);

  const onBack = (): void => {
    setNotice(null);
    if (step === 'pin') {
      setPin('');
      setStep('phone');
    } else {
      route('/');
    }
  };

  const isPhone = step === 'phone';

  return (
    <CitizenShell onBack={busy ? undefined : onBack} prompt={isPhone ? 'login_phone_hint' : 'login_pin_hint'}>
      <div class="flex items-center gap-4">
        <Pictogram name={isPhone ? 'phone' : 'lock'} size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t(isPhone ? 'login_phone_title' : 'login_pin_title')}
        </h1>
      </div>
      <p id="login-hint" class="text-lg text-ink-muted">
        {t(isPhone ? 'login_phone_hint' : 'login_pin_hint')}
      </p>
      {isPhone && vaultState.value === 'locked' ? (
        // Answers sealed on this phone wait for their owner's PIN (they are sent after sign-in).
        <p class="flex items-center gap-2 rounded-lg border-2 border-info bg-info-soft p-2 text-base font-semibold text-info-strong">
          <Pictogram name="phone-saved" size={28} />
          <span class="flex-1">{t('login_send_saved')}</span>
        </p>
      ) : null}

      {isPhone ? <PhoneDisplay local={local} noted={notice?.key === 'phone_not_mock'} /> : <PinDisplay length={pin.length} local={local} />}

      {notice ? (
        <div role="alert" class="flex items-start gap-3 rounded-lg border-2 border-danger bg-danger-soft p-3 text-danger">
          <Pictogram name="warning" size={32} />
          <div class="flex flex-1 flex-col items-start gap-2">
            <p class="text-lg font-semibold">{t(notice.key)}</p>
            {notice.requestId ? <p class="text-sm">{t('state_reference', { id: notice.requestId })}</p> : null}
            <AudioPrompt prompt={notice.key} />
          </div>
        </div>
      ) : null}

      {busy ? (
        <p role="status" class="text-center text-lg text-ink-muted">
          {t('login_checking')}
        </p>
      ) : null}

      <Keypad
        onDigit={onDigit}
        onDelete={onDelete}
        onDone={onDone}
        doneEnabled={isPhone ? local.length === PHONE_LENGTH : pin.length >= PIN_MIN}
        disabled={busy}
        busy={busy}
      />

      {demoMode.value ? (
        <p class="text-center text-sm" lang="en" dir="ltr">
          <a href="/demo" class="text-info-strong underline">
            Demo accounts
          </a>
        </p>
      ) : null}
    </CitizenShell>
  );
}

function PhoneDisplay({ local, noted }: { local: string; noted: boolean }) {
  const refused = checkPhone(local) === 'not_mock';
  return (
    <div class="flex flex-col gap-2">
      <p class="text-lg font-semibold" id="phone-label">
        {t('login_phone_label')}
      </p>
      <PhoneSlots digits={local} labelledBy="phone-label" invalid={refused} />
      {refused && !noted ? (
        <p class="flex items-center gap-2 text-base font-semibold text-danger">
          <Pictogram name="warning" size={24} />
          {t('phone_not_mock')}
        </p>
      ) : null}
    </div>
  );
}

function PinDisplay({ length, local }: { length: number; local: string }) {
  return (
    <div class="flex flex-col gap-2">
      <p class="rh-ltr text-center font-mono text-lg text-ink-muted">{formatPhone(local)}</p>
      <PinDots count={length} />
    </div>
  );
}
