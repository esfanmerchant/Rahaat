import './ussd.css';
import { useEffect, useState } from 'preact/hooks';
import { Emblem } from '../shared/components/Emblem';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { Phone } from './Phone';
import { loadPersonas, RelayError, type Persona, type PersonasOut, type RelayFailure } from './relay';
import { SmsPanel } from './SmsPanel';
import { SERVICE_CODE, usePhone } from './usePhone';

type Load = { kind: 'loading' } | { kind: 'ready'; data: PersonasOut } | { kind: 'failed'; reason: RelayFailure };

const STEPS: { title: string; body: string }[] = [
  { title: 'Dial', body: 'Press Dial *786# under the phone, or type it on the keys and press the green key.' },
  { title: 'Choose a language', body: '1 is English. 2 is Roman Urdu, because many feature phones cannot show Urdu script.' },
  { title: 'Pick a service', body: '1 checks an application, 2 checks a message, 3 stops sharing your data, 4 asks a person to call.' },
  { title: 'Go back', body: '0 goes back one screen. 00 goes to the main menu. The session ends after 3 minutes.' },
];

function codeDigits(persona: Persona | undefined): string | null {
  return persona?.tracking_code ? persona.tracking_code.replace(/\D/g, '') : null;
}

function FailureCard({ reason, onRetry }: { reason: RelayFailure; onRetry: () => void }) {
  const text =
    reason === 'unavailable'
      ? 'The feature-phone simulator is only available in the demo, not in production.'
      : reason === 'offline'
        ? 'No network. Check your connection.'
        : reason === 'busy'
          ? 'Too many requests. Wait a minute.'
          : 'The simulator could not start.';
  return (
    <div role="alert" class="mx-auto my-16 flex max-w-md flex-col items-center gap-4 rounded-2xl border border-night-line bg-night-2 p-6 text-center">
      <Emblem size={56} tone="night" />
      <p class="m-0 text-lg font-bold">{text}</p>
      {reason !== 'unavailable' ? (
        <button
          type="button"
          onClick={onRetry}
          class="min-h-12 rounded-lg border border-noor bg-night-3 px-5 font-bold text-noor focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

function Simulator({ data }: { data: PersonasOut }) {
  const [msisdn, setMsisdn] = useState(data.personas[0]?.msisdn ?? '');
  const persona = data.personas.find((p) => p.msisdn === msisdn);
  const phone = usePhone(msisdn);
  const digits = codeDigits(persona);

  // The computer keyboard works as the keypad: digits, * and #, Enter to send, Backspace, Escape to end. Letters
  // go to the phone only in a session (verify codes have letters); typing in the SMS box is left alone.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (el && el.tagName === 'BUTTON' && (e.key === 'Enter' || e.key === ' ')) return; // the focused button handles it
      if (/^[0-9*#]$/.test(e.key)) {
        e.preventDefault();
        phone.press(e.key);
      } else if (/^[a-zA-Z]$/.test(e.key)) {
        phone.letter(e.key);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        phone.call();
      } else if (e.key === 'Backspace') {
        e.preventDefault();
        phone.backspace();
      } else if (e.key === 'Escape') {
        phone.end();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phone.press, phone.letter, phone.call, phone.backspace, phone.end]);

  return (
    <div class="mx-auto grid w-full max-w-[1680px] items-start gap-6 px-4 pb-8 pt-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:gap-x-10 lg:gap-y-4 lg:px-10 lg:pt-6">
      <section aria-label="Who is calling" class="order-1 lg:col-start-1 lg:row-start-1">
        <div role="radiogroup" aria-label="Demo phone number" class="flex flex-wrap gap-2">
          {data.personas.map((p) => (
            <button
              key={p.msisdn}
              type="button"
              role="radio"
              aria-checked={p.msisdn === msisdn}
              onClick={() => setMsisdn(p.msisdn)}
              class={`min-h-14 min-w-0 flex-1 rounded-xl border px-4 py-2 text-start focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor ${
                p.msisdn === msisdn ? 'border-noor bg-night-3 shadow-glow' : 'border-night-line bg-night-2 hover:border-night-muted'
              }`}
            >
              <span class="block text-base font-bold">{p.name}</span>
              <span class="block font-mono text-sm text-night-muted">{p.display}</span>
            </button>
          ))}
        </div>
      </section>

      <section aria-label="What to try" class="order-4 flex flex-col gap-4 lg:col-start-1 lg:row-start-2">
        <div class="rounded-2xl border border-night-line bg-night-1/80 p-4">
          <h2 class="m-0 text-base font-bold">What to try</h2>
          <dl class="m-0 mt-3 grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-2 text-sm">
            <dt class="text-night-muted">Tracking code</dt>
            <dd class="m-0">
              {persona?.tracking_code ? (
                <>
                  <span class="font-mono text-base font-bold text-noor">{persona.tracking_code}</span>{' '}
                  <span class="text-night-muted">({persona.symbols.join(' ')})</span>
                  <span class="block text-night-muted">Type {digits} at option 1.</span>
                </>
              ) : (
                <span class="text-night-muted">None yet. Start an application in the citizen app first.</span>
              )}
            </dd>
            <dt class="text-night-muted">PIN</dt>
            <dd class="m-0 font-mono text-base font-bold text-noor">{data.demo_pin}</dd>
            <dt class="text-night-muted">Message code</dt>
            <dd class="m-0">Send HELP in the text box, then type the 6 characters after the word Code at option 2.</dd>
          </dl>
          <p class="m-0 mt-3 rounded-lg border border-saffron/40 bg-saffron/10 px-3 py-2 text-sm text-night-ink">
            Option 3 really stops sharing this person's data. They can allow it again in the citizen app.
          </p>
        </div>

        <ol class="m-0 flex list-none flex-col gap-2 p-0">
          {STEPS.map((s, i) => (
            <li key={s.title} class="flex gap-3 rounded-xl border border-night-line bg-night-1/60 px-4 py-3">
              <span class="flex size-7 shrink-0 items-center justify-center rounded-full bg-noor font-black text-night" aria-hidden="true">
                {i + 1}
              </span>
              <p class="m-0 text-sm text-night-muted">
                <b class="text-night-ink">{s.title}. </b>
                {s.body}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-label="Feature phone" class="order-2 flex flex-col items-center gap-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
        <Phone phone={phone} display={persona?.display ?? ''} />
        <div class="flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={phone.quickDial}
            disabled={phone.busy || phone.mode === 'session'}
            class="min-h-12 rounded-lg border border-noor bg-night-3 px-5 text-base font-bold text-noor shadow-glow hover:bg-night-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor disabled:opacity-50 disabled:shadow-none"
          >
            Dial {SERVICE_CODE}
          </button>
          <p class="m-0 flex items-center text-sm text-night-muted">Keyboard works too: digits, Enter to send, Esc to end.</p>
        </div>
      </section>

      <div class="order-3 lg:col-start-3 lg:row-span-2 lg:row-start-1">
        <SmsPanel msisdn={msisdn} display={persona?.display ?? ''} trackingDigits={digits} pin={data.demo_pin} />
      </div>
    </div>
  );
}

/** /ussd: a feature phone on a desk in the dark. USSD menu and SMS commands for people without a smartphone. */
export default function UssdPage() {
  const [state, setState] = useState<Load>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setState({ kind: 'loading' });
    loadPersonas()
      .then((data) => alive && setState({ kind: 'ready', data }))
      .catch((error: unknown) => alive && setState({ kind: 'failed', reason: error instanceof RelayError ? error.kind : 'error' }));
    return () => {
      alive = false;
    };
  }, [attempt]);

  return (
    <div dir="ltr" lang="en" class="ussd-stage flex flex-col">
      <header class="flex items-center gap-3 px-4 pt-3 lg:gap-4 lg:px-10 lg:pt-5">
        <Emblem size={40} tone="night" animate />
        <div class="min-w-0">
          <h1 class="m-0 text-lg font-black leading-tight tracking-tight lg:text-2xl">Rahat on a feature phone</h1>
          <p class="m-0 text-xs text-night-muted lg:text-sm">Dial {SERVICE_CODE} or send a text. No smartphone, no data plan, no app.</p>
        </div>
        <a
          href="/demo"
          class="ms-auto min-h-12 shrink-0 content-center rounded-lg border border-night-line px-4 text-sm font-bold text-night-ink hover:border-noor focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor"
        >
          Demo
        </a>
      </header>
      <main class="flex-1">
        {state.kind === 'loading' ? (
          <p role="status" class="mx-auto my-24 text-center text-night-muted">
            Switching the phone on…
          </p>
        ) : state.kind === 'failed' ? (
          <FailureCard reason={state.reason} onRetry={() => setAttempt((n) => n + 1)} />
        ) : state.data.personas.length === 0 ? (
          <FailureCard reason="error" onRetry={() => setAttempt((n) => n + 1)} />
        ) : (
          <Simulator data={state.data} />
        )}
      </main>
      <PrototypeFooter density="staff" tone="night" />
    </div>
  );
}
