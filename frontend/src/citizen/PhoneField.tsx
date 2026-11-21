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
 * `big` is for the helper screen's larger text.
 */
export function PhoneSlots({ digits, labelledBy, invalid = false }: { digits: string; labelledBy: string; invalid?: boolean }) {
  const slots = Array.from({ length: PHONE_LENGTH }, (_, index) => digits[index] ?? '');
  return (
    <div
      role="status"
      aria-labelledby={labelledBy}
      class={`rh-ltr flex min-h-tap-lg items-center justify-center gap-0.5 rounded-xl border-2 bg-paper px-2 font-mono text-xl font-bold sm:text-2xl ${invalid ? 'border-danger' : 'border-line-strong'}`}
    >
      <span class="me-2 whitespace-nowrap rounded-md bg-surface px-2 text-ink-muted">{SHOWN_PHONE_PREFIX}</span>
      {slots.map((digit, index) => (
        <span
          key={index}
          aria-hidden="true"
          class={`inline-block w-[0.85em] text-center ${digit ? 'text-ink' : 'border-b-4 border-line text-transparent'}`}
        >
          {digit || '0'}
        </span>
      ))}
      <span class="sr-only">{formatPhone(digits)}</span>
    </div>
  );
}
