import { useEffect, useState } from 'preact/hooks';
import { Emblem } from '../shared/components/Emblem';
import { KEY_LETTERS, SERVICE_CODE, SESSION_SECONDS, type PhoneApi } from './usePhone';

/** Everything is placed in a 300 x 620 box so the phone scales as one piece (CSS container units in ussd.css). */
const W = 300;
const H = 620;
const box = (x: number, y: number, w: number, h: number) => ({
  left: `${(x / W) * 100}%`,
  top: `${(y / H) * 100}%`,
  width: `${(w / W) * 100}%`,
  height: `${(h / H) * 100}%`,
});

const ROWS: string[][] = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['*', '0', '#'],
];

function Handset({ kind }: { kind: 'call' | 'end' }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false" class={kind === 'end' ? 'rotate-[135deg]' : ''}>
      <path
        d="M20 15.5c-1.25 0-2.45-.2-3.57-.570a1 1 0 0 0-1.02.240l-2.2 2.2a15.045 15.045 0 0 1-6.59-6.59l2.2-2.2a.96.96 0 0 0 .250-1A11.36 11.36 0 0 1 8.5 4c0-.550-.450-1-1-1H4c-.550 0-1 .450-1 1 0 9.39 7.61 17 17 17 .550 0 1-.450 1-1v-3.5c0-.550-.450-1-1-1z"
        fill="currentColor"
      />
    </svg>
  );
}

function Signal() {
  return (
    <svg viewBox="0 0 18 12" width="18" height="12" aria-hidden="true" focusable="false">
      {[3, 6, 9, 12].map((h, i) => (
        <rect key={h} x={i * 4.5} y={12 - h} width="3" height={h} fill="currentColor" />
      ))}
    </svg>
  );
}

function Battery() {
  return (
    <svg viewBox="0 0 22 12" width="22" height="12" aria-hidden="true" focusable="false">
      <rect x="0.5" y="1.5" width="18" height="9" fill="none" stroke="currentColor" />
      <rect x="19" y="4" width="2.5" height="4" fill="currentColor" />
      <rect x="2" y="3" width="12" height="6" fill="currentColor" />
    </svg>
  );
}

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15000);
    return () => window.clearInterval(id);
  }, []);
  return now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

const FAILURE_TEXT = {
  offline: 'No network.\nCheck your\nconnection.',
  unavailable: 'The simulator is\nswitched off here.\n(Demo mode only)',
  busy: 'Too many requests.\nWait a minute\nand try again.',
  error: 'Service busy.\nTry again.',
} as const;

function softLabels(p: PhoneApi): [string, string] {
  if (p.mode === 'ended') return ['OK', ''];
  if (p.mode === 'session') return ['Send', 'Cancel'];
  return ['Dial *786#', 'Clear'];
}

/** The simulated handset: a generic feature phone drawn in SVG and CSS, with a lit LCD and a working keypad. */
export function Phone({ phone, display }: { phone: PhoneApi; display: string }) {
  const clock = useClock();
  const [left, right] = softLabels(phone);
  const timeLeft = phone.secondsLeft;
  const ratio = timeLeft === null ? 0 : timeLeft / SESSION_SECONDS;
  const minutes = timeLeft === null ? '' : `${Math.floor(timeLeft / 60)}:${String(timeLeft % 60).padStart(2, '0')}`;
  const body = phone.failure ? FAILURE_TEXT[phone.failure] : phone.mode === 'idle' ? '' : phone.text;

  return (
    <div class="ussd-phone" data-busy={phone.busy ? '1' : '0'}>
      <svg class="ussd-chassis" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="ussd-body" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#232f66" />
            <stop offset="0.5" stop-color="#151d45" />
            <stop offset="1" stop-color="#0b1026" />
          </linearGradient>
          <linearGradient id="ussd-rim" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#ffd36e" stop-opacity="0.75" />
            <stop offset="0.5" stop-color="#ffd36e" stop-opacity="0.12" />
            <stop offset="1" stop-color="#ffd36e" stop-opacity="0.45" />
          </linearGradient>
          <linearGradient id="ussd-plate" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#0f1736" />
            <stop offset="1" stop-color="#0a0f26" />
          </linearGradient>
        </defs>
        <path
          d={`M46 1.5H254Q298.5 1.5 298.5 46V548Q298.5 618.5 228 618.5H72Q1.5 618.5 1.5 548V46Q1.5 1.5 46 1.5Z`}
          fill="url(#ussd-body)"
          stroke="url(#ussd-rim)"
          stroke-width="3"
        />
        {/* Speaker slot, and the screen's glass frame. */}
        <rect x="112" y="16" width="76" height="6" rx="3" fill="#05081a" stroke="#2a3570" />
        <rect x="19" y="34" width="262" height="218" rx="16" fill="#05081a" stroke="#2a3570" stroke-width="2" />
        {/* Navigation cluster: ring and arrows (the centre key is a real button). */}
        <circle cx="150" cy="292" r="36" fill="#0f1736" stroke="#2a3570" stroke-width="2" />
        <g fill="#8ea2ff" opacity="0.7">
          <path d="M150 262l7 9h-14z" />
          <path d="M150 322l7-9h-14z" />
          <path d="M120 292l9-7v14z" />
          <path d="M180 292l-9-7v14z" />
        </g>
        {/* Keypad plate. */}
        <rect x="16" y="346" width="268" height="204" rx="18" fill="url(#ussd-plate)" stroke="#1b2552" />
        <g transform="translate(150 584)">
          <circle r="21" fill="none" stroke="#2a3570" />
        </g>
      </svg>

      {/* The lit LCD. */}
      <div class="ussd-lcd" style={box(27, 42, 246, 202)} role="region" aria-label="Phone screen">
        <div class="ussd-lcd-status" aria-hidden="true">
          <Signal />
          <span class="ussd-lcd-net">RAHAT-MOCK</span>
          <span class="ussd-lcd-mode">{phone.mode === 'session' ? phone.inputMode : ''}</span>
          <Battery />
        </div>
        <div class="ussd-lcd-body" aria-live="polite" aria-atomic="true">
          {phone.mode === 'idle' && !phone.failure ? (
            <div class="ussd-lcd-idle">
              <p class="ussd-lcd-clock">{clock}</p>
              <p class="ussd-lcd-sub">{display}</p>
              {phone.notice === 'wrong_code' ? <p class="ussd-lcd-note">Not a Rahat code. Dial {SERVICE_CODE}</p> : <p class="ussd-lcd-sub">Rahat (prototype)</p>}
            </div>
          ) : (
            <pre class="ussd-lcd-text">{phone.busy && !body ? 'Please wait…' : body}</pre>
          )}
        </div>
        {phone.mode === 'session' && !phone.failure ? (
          <div class="ussd-lcd-timer" role="img" aria-label={`Session time left ${minutes}`}>
            <span style={{ width: `${Math.round(ratio * 100)}%` }} />
          </div>
        ) : null}
        <div class="ussd-lcd-input" aria-label="Typed so far">
          <span class="ussd-lcd-prompt" aria-hidden="true">
            {phone.mode === 'ended' ? '' : '>'}
          </span>
          <span class="ussd-lcd-typed">{phone.mode === 'ended' ? '' : phone.buffer}</span>
          {phone.mode !== 'ended' ? <span class="ussd-lcd-caret" aria-hidden="true" /> : null}
          {phone.busy ? <span class="ussd-lcd-wait">…</span> : null}
        </div>
        <div class="ussd-lcd-soft" aria-hidden="true">
          <span>{left}</span>
          <span>{right}</span>
        </div>
      </div>

      {/* Soft keys, call, end, centre key. */}
      <button type="button" class="ussd-key ussd-soft" style={box(26, 262, 72, 30)} aria-label={left || 'Soft key'} disabled={!left} onClick={phone.mode === 'idle' ? phone.quickDial : phone.call}>
        <span aria-hidden="true" />
      </button>
      <button type="button" class="ussd-key ussd-soft" style={box(202, 262, 72, 30)} aria-label={right || 'Soft key'} disabled={!right} onClick={phone.end}>
        <span aria-hidden="true" />
      </button>
      <button type="button" class="ussd-key ussd-ok" style={box(130, 272, 40, 40)} aria-label="OK (send)" onClick={phone.call}>
        <span aria-hidden="true" />
      </button>
      <button
        type="button"
        class="ussd-key ussd-call"
        style={box(24, 306, 70, 38)}
        aria-label={phone.mode === 'idle' ? 'Call (dial the number typed)' : phone.mode === 'ended' ? 'OK' : 'Send'}
        data-pressed={phone.pressed === 'call' ? '1' : '0'}
        onClick={phone.call}
      >
        <Handset kind="call" />
      </button>
      <button type="button" class="ussd-key ussd-endkey" style={box(206, 306, 70, 38)} aria-label="End or clear" onClick={phone.end}>
        <Handset kind="end" />
      </button>

      {ROWS.map((row, r) =>
        row.map((key, c) => (
          <button
            key={key}
            type="button"
            class="ussd-key ussd-num"
            data-pressed={phone.pressed === key ? '1' : '0'}
            style={box(24 + c * 90, 354 + r * 48, 80, 42)}
            aria-label={key === '*' ? 'Star' : key === '#' ? 'Hash' : `${key}${KEY_LETTERS[key] ? ` ${KEY_LETTERS[key]}` : ''}`}
            onClick={() => phone.press(key)}
          >
            <b>{key}</b>
            {KEY_LETTERS[key] ? <small aria-hidden="true">{KEY_LETTERS[key]}</small> : null}
          </button>
        )),
      )}

      <div class="ussd-brand" style={box(80, 556, 140, 44)} aria-hidden="true">
        <Emblem size={26} tone="night" />
        <span>RAHAT</span>
      </div>
    </div>
  );
}
