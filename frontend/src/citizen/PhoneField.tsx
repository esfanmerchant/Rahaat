import { useEffect } from 'preact/hooks';
import { formatPhone, normalizePhone, PHONE_LENGTH, SHOWN_PHONE_PREFIX } from './phone';

/** Paste a number anywhere on the screen: `+92 999...`, `92999...`, `0999-...` or `0999...` all become ten digits. */
export function usePhonePaste(onDigits: (digits: string) => void, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return undefined;
    const onPaste = (event: ClipboardEvent): void => {
      const text = event.clipboardData?.getData('text') ?? '';
      if (!/\d/.test(text)) return;
      event.preventDefault();
      onDigits(normalizePhone(text));
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [onDigits, enabled]);
}

/**
 * The phone display: a fixed +92 prefix and ten slots. Always left to right, in every language.
 * With `length` (the sign-up code), only that many slots and no prefix.
 */
export function PhoneSlots({ digits, labelledBy, invalid = false, length = PHONE_LENGTH }: { digits: string; labelledBy: string; invalid?: boolean; length?: number }) {
  const phone = length === PHONE_LENGTH;
  const slots = Array.from({ length }, (_, index) => digits[index] ?? '');
  return (
    <div
      role="status"
      aria-labelledby={labelledBy}
      class={`rh-ltr flex min-h-tap-lg items-center justify-center gap-0.5 rounded-xl border-2 bg-paper px-2 font-mono text-xl font-bold sm:text-2xl ${invalid ? 'border-danger' : 'border-line-strong'}`}
    >
      {phone ? <span class="me-2 whitespace-nowrap rounded-md bg-surface px-2 text-ink-muted">{SHOWN_PHONE_PREFIX}</span> : null}
      {slots.map((digit, index) => (
        <span
          key={index}
          aria-hidden="true"
          class={`inline-block w-[0.85em] text-center ${digit ? 'text-ink' : 'border-b-4 border-line text-transparent'}`}
        >
          {digit || '0'}
        </span>
      ))}
      <span class="sr-only">{phone ? formatPhone(digits) : digits}</span>
    </div>
  );
}
