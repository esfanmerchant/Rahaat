import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { login, session } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call, type ApiFailure } from '../shared/api/problem';
import { playPrompt } from '../shared/audio';
import { Button } from '../shared/components/Button';
import { Pictogram, type PictogramName } from '../shared/components/Pictogram';
import { celebrate } from '../shared/feedback';
import { lang, t, type MessageKey } from '../shared/i18n';
import { Redirect } from '../shared/routing';
import { CitizenShell } from './CitizenShell';
import { Keypad, PinDots } from './Keypad';
import { buzz, NoticeBox, PhoneDisplay, sayDigit, type Notice } from './LoginScreen';
import { PhoneSlots, usePhonePaste } from './PhoneField';
import { checkPhone, formatPhone, mockPhone, PHONE_LENGTH, PIN_MAX, PIN_MIN } from './phone';

/** A new account joins the prototype's main department (see backend/app/demo_accounts.py). */
const TENANT = 'sindh-relief';
const CODE_LENGTH = 6;

type Step = 'phone' | 'code' | 'name' | 'pin' | 'again' | 'done';
const ORDER: readonly Step[] = ['phone', 'code', 'name', 'pin', 'again', 'done'];

const SPEC: Record<Step, { icon: PictogramName; title: MessageKey; hint: MessageKey }> = {
  phone: { icon: 'phone', title: 'signup_title', hint: 'login_phone_hint' },
  code: { icon: 'message', title: 'signup_code_title', hint: 'signup_code_hint' },
  name: { icon: 'person', title: 'signup_name_title', hint: 'signup_name_hint' },
  pin: { icon: 'lock', title: 'signup_pin_title', hint: 'signup_pin_hint' },
  again: { icon: 'lock', title: 'signup_pin_title', hint: 'pin_again' },
  done: { icon: 'yes', title: 'signup_done_title', hint: 'signup_done_body' },
};

/** What a refusal means here, in plain words. The server answers the same for a wrong, old or used code. */
function noticeFor(failure: ApiFailure): Notice {
  const kind = failure.kind;
  const code = failure.problem?.code;
  const key: MessageKey =
    kind === 'rate_limited' || kind === 'locked'
      ? 'login_locked'
      : kind === 'offline' || kind === 'network'
        ? 'state_offline_body'
        : code === 'invalid_code'
          ? 'signup_code_wrong'
          : code === 'weak_pin'
            ? 'signup_pin_weak'
            : 'state_error_body';
  return { key, requestId: key === 'state_error_body' ? failure.problem?.request_id : undefined };
}

/**
 * Make an account: the phone number, the six-number code from the SMS, the name, a PIN typed twice;
 * then the person is signed in. The code is never shown here: the SMS is the only place it appears
 * (simulated in this prototype; an admin reads it under Mock services). A number that already has an
 * account gets the same answer and an SMS that says "sign in instead", so this screen never tells
 * anyone who is registered.
 */
export function SignupScreen() {
  const { route } = useLocation();
  const [step, setStep] = useState<Step>('phone');
  const [local, setLocal] = useState('');
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [pin, setPin] = useState('');
  const [first, setFirst] = useState('');
  const [registration, setRegistration] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // What the speaker says on arriving at a step: why the person was sent back (if so), then the step's hint.
  const [say, setSay] = useState<{ id: string; keys: MessageKey[] }>({ id: 'phone', keys: ['login_phone_hint'] });
  const headingRef = useRef<HTMLHeadingElement>(null);
  const ui = lang.value;

  // Each step is its own screen: the heading takes the focus, so a screen reader reads the new question.
  useEffect(() => headingRef.current?.focus(), [step]);

  /** A problem on this step, said at once. */
  const show = (next: Notice): void => {
    setNotice(next);
    playPrompt(next.key, ui, t(next.key, undefined, ui));
  };

  const go = (next: Step, why: Notice | null = null): void => {
    setStep(next);
    setNotice(why);
    setSay({ id: `${next}:${Date.now()}`, keys: why ? [why.key, SPEC[next].hint] : [SPEC[next].hint] });
  };

  const sendCode = async (): Promise<void> => {
    setBusy(true);
    const result = await call(api.POST('/v1/people/register/start', { body: { tenant_slug: TENANT, phone: mockPhone(local), lang: ui } }));
    setBusy(false);
    if (!result.ok) return show(noticeFor(result.failure));
    setRegistration(result.data.registration_id);
    setCode('');
    go('code');
  };

  const finish = async (): Promise<void> => {
    setBusy(true);
    const full = name.trim();
    const result = await call(
      api.POST('/v1/people/register/complete', {
        body: {
          tenant_slug: TENANT,
          registration_id: registration,
          code,
          full_name: full,
          // A name typed in Urdu letters is kept as the Urdu spelling too.
          ...(/[؀-ۿ]/.test(full) ? { full_name_ur: full } : {}),
          pin,
        },
      }),
    );
    if (!result.ok) {
      setBusy(false);
      const why = noticeFor(result.failure);
      setPin('');
      if (why.key === 'signup_code_wrong') {
        setFirst('');
        setCode('');
        go('code', why);
      } else if (why.key === 'signup_pin_weak') {
        setFirst('');
        go('pin', why);
      } else show(why); // no network, or a server problem: type the second PIN again to retry
      return;
    }
    // Signed in at once with the new PIN (this also opens the person's sealed store on this phone).
    await login({ identifier: mockPhone(local), secret: pin, tenant_slug: TENANT });
    setBusy(false);
    go('done');
    celebrate();
  };

  const setValue = step === 'phone' ? setLocal : step === 'code' ? setCode : setPin;
  const value = step === 'phone' ? local : step === 'code' ? code : pin;
  const limit = step === 'phone' ? PHONE_LENGTH : step === 'code' ? CODE_LENGTH : PIN_MAX;

  const onDigit = useCallback(
    (digit: string) => {
      if (busy) return;
      setNotice(null);
      buzz();
      setValue((typed) => (typed.length < limit ? typed + digit : typed));
      // Digits of the number and of the code are said aloud; PIN digits never are.
      if (step === 'phone' || step === 'code') sayDigit(digit, ui);
    },
    [busy, step, ui],
  );

  const onDelete = useCallback(() => {
    if (busy) return;
    setNotice(null);
    buzz();
    setValue((typed) => typed.slice(0, -1));
  }, [busy, step]);

  usePhonePaste(
    useCallback((digits: string) => {
      setNotice(null);
      setLocal(digits);
    }, []),
    step === 'phone' && !busy,
  );

  const onDone = (): void => {
    if (busy) return;
    if (step === 'phone') {
      const check = checkPhone(local);
      if (check === 'ok') void sendCode();
      else show({ key: check === 'not_mock' ? 'phone_not_mock' : 'login_phone_invalid' });
    } else if (step === 'code') go('name');
    else if (step === 'pin') {
      setFirst(pin);
      setPin('');
      go('again');
    } else if (pin === first) void finish();
    else {
      setPin('');
      setFirst('');
      go('pin', { key: 'pin_differs' });
    }
  };

  const back = (): void => {
    setPin('');
    setFirst('');
    if (step === 'phone') route('/login');
    else go(ORDER[ORDER.indexOf(step) - 1] ?? 'phone');
  };

  // Signed in meanwhile (another tab, or back after the account was made): nothing to do here.
  if (session.value.status === 'signed-in' && step !== 'done' && !busy) return <Redirect to="/" />;

  const spec = SPEC[step];
  const at = Math.min(ORDER.indexOf(step), 3);
  return (
    <CitizenShell
      onBack={busy || step === 'done' ? undefined : back}
      speech={{ id: say.id, items: say.keys.map((key) => ({ key, text: t(key, undefined, ui) })), lang: ui }}
      progress={
        step === 'done' ? null : (
          <div
            role="progressbar"
            aria-valuemin={1}
            aria-valuemax={4}
            aria-valuenow={at + 1}
            aria-label={t('apply_progress', { current: at + 1, total: 4 })}
            class="flex justify-center gap-2 py-1"
          >
            {[0, 1, 2, 3].map((i) => (
              <span key={i} class={`size-3 rounded-full border-2 ${i <= at ? 'border-primary bg-primary' : 'border-ink-muted'}`} />
            ))}
          </div>
        )
      }
    >
      <div class="flex items-center gap-4">
        <Pictogram name={spec.icon} size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t(spec.title)}
        </h1>
      </div>
      <p id="signup-hint" class="text-lg text-ink-muted">
        {t(spec.hint)}
      </p>

      {step === 'phone' ? <PhoneDisplay local={local} noted={notice?.key === 'phone_not_mock'} /> : null}
      {step === 'code' ? (
        <>
          <p class="rh-ltr text-center font-mono text-lg text-ink-muted">{formatPhone(local)}</p>
          <PhoneSlots digits={code} labelledBy="signup-hint" length={CODE_LENGTH} />
        </>
      ) : null}
      {step === 'pin' || step === 'again' ? <PinDots count={pin.length} /> : null}
      {step === 'name' ? (
        <form
          class="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim().length >= 2) go('pin');
          }}
        >
          <label for="signup-name" class="text-lg font-semibold">
            {t('review_name')}
          </label>
          {/* What is typed stays text: it never goes into the page as HTML. */}
          <input
            id="signup-name"
            type="text"
            autocomplete="name"
            dir="auto"
            maxLength={200}
            value={name}
            onInput={(event) => setName(event.currentTarget.value)}
            class="min-h-tap-lg rounded-lg border-2 border-line-strong bg-paper px-3 text-xl"
          />
          <Button size="lg" icon="forward" block type="submit" disabled={name.trim().length < 2}>
            {t('next')}
          </Button>
        </form>
      ) : null}

      {notice ? <NoticeBox notice={notice} /> : null}
      {busy ? (
        <p role="status" class="text-center text-lg text-ink-muted">
          {t('login_checking')}
        </p>
      ) : null}

      {step === 'name' || step === 'done' ? null : (
        <Keypad
          onDigit={onDigit}
          onDelete={onDelete}
          onDone={onDone}
          doneEnabled={value.length >= (step === 'phone' ? PHONE_LENGTH : step === 'code' ? CODE_LENGTH : PIN_MIN)}
          disabled={busy}
          busy={busy}
        />
      )}

      {step === 'code' ? (
        <div class="flex flex-col gap-3">
          <p class="text-base text-ink-muted">{t('signup_code_exists')}</p>
          <Button size="md" variant="secondary" icon="message" block disabled={busy} onClick={() => void sendCode()}>
            {t('signup_code_new')}
          </Button>
          <Button size="md" variant="quiet" icon="person" block onClick={() => route('/login')}>
            {t('sign_in')}
          </Button>
          {/* The honest line for this prototype: no real SMS is sent. */}
          <p class="rounded-lg border border-line bg-surface p-2 text-sm text-ink-muted">{t('signup_code_sim')}</p>
        </div>
      ) : null}

      {step === 'done' ? (
        <Button size="lg" icon="home" block onClick={() => route(session.peek().status === 'signed-in' ? '/' : '/login', true)}>
          {t(session.value.status === 'signed-in' ? 'go_home' : 'sign_in')}
        </Button>
      ) : null}
    </CitizenShell>
  );
}
