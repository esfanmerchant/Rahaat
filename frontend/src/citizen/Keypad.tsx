import { useEffect } from 'preact/hooks';
import { Pictogram } from '../shared/components/Pictogram';
import { Spinner } from '../shared/components/Spinner';
import { t } from '../shared/i18n';
import { PIN_MIN } from './phone';

/**
 * How much of a PIN is typed: four dots, because most PINs have four numbers. A fifth and a sixth dot
 * appear only when the person types them (a PIN has 4 to 6 numbers). The digits are never shown.
 */
export function PinDots({ count, label = t('login_pin_label') }: { count: number; label?: string }) {
  return (
    <div
      role="status"
      aria-label={`${label}: ${t('login_pin_progress', { count })}`}
      class="rh-ltr flex min-h-tap-lg items-center justify-center gap-4 rounded-lg border-2 border-line-strong bg-paper px-3"
    >
      {Array.from({ length: Math.max(PIN_MIN, count) }, (_, index) => (
        <span key={index} aria-hidden="true" class={`inline-block size-5 rounded-full border-2 ${index < count ? 'border-ink bg-ink' : 'border-ink-muted'}`} />
      ))}
    </div>
  );
}

interface KeypadProps {
  onDigit: (digit: string) => void;
  onDelete: () => void;
  onDone: () => void;
  doneEnabled: boolean;
  disabled?: boolean;
  busy?: boolean;
}

const ROWS = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
] as const;

const KEY =
  'flex min-h-tap-lg items-center justify-center rounded-lg border-2 text-3xl font-bold ' +
  'disabled:cursor-not-allowed disabled:text-ink-subtle';
const DIGIT_KEY = `${KEY} border-line-strong bg-surface text-ink hover:bg-sunken active:bg-primary-soft`;

/**
 * Large phone-style keypad. Always laid out left to right (dir="ltr"), as on
 * every phone, even when the screen is in Urdu. Physical keys 0-9, Backspace
 * and Enter work too.
 */
export function Keypad({ onDigit, onDelete, onDone, doneEnabled, disabled = false, busy = false }: KeypadProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (disabled || event.ctrlKey || event.metaKey || event.altKey) return;
      if (/^[0-9]$/.test(event.key)) {
        event.preventDefault();
        onDigit(event.key);
      } else if (event.key === 'Backspace') {
        event.preventDefault();
        onDelete();
      } else if (event.key === 'Enter' && doneEnabled) {
        event.preventDefault();
        onDone();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onDigit, onDelete, onDone, doneEnabled, disabled]);

  const digit = (value: string) => (
    <button key={value} type="button" class={DIGIT_KEY} disabled={disabled} onClick={() => onDigit(value)}>
      {value}
    </button>
  );

  return (
    <div dir="ltr" class="grid grid-cols-3 gap-3" role="group" aria-label={t('keypad_label')}>
      {ROWS.map((row) => row.map(digit))}
      <button
        type="button"
        class={`${KEY} border-line-strong bg-paper text-ink hover:bg-surface`}
        disabled={disabled}
        onClick={onDelete}
        aria-label={t('keypad_delete')}
      >
        {/* Digits run left to right, so backspace always points left, even in Urdu. */}
        <Pictogram name="delete" size={36} mirror={false} />
      </button>
      {digit('0')}
      <button
        type="button"
        class={`${KEY} border-primary bg-primary text-white hover:bg-primary-strong disabled:border-line disabled:bg-surface`}
        disabled={disabled || !doneEnabled}
        onClick={onDone}
        aria-label={t('keypad_done')}
        aria-busy={busy || undefined}
      >
        {busy ? <Spinner size={36} /> : <Pictogram name="yes" size={40} />}
      </button>
    </div>
  );
}
