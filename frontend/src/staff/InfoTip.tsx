import { useEffect, useId, useRef, useState } from 'preact/hooks';

/** A small "i" button that opens a short popover (also a title for hover). Click outside or Escape closes it. */
export function InfoTip({ text, label = 'More info' }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return undefined;
    const away = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  return (
    <span class="cc-tip" ref={box}>
      <button type="button" class="cc-tip-btn" aria-label={label} aria-expanded={open} aria-controls={open ? id : undefined} title={text} onClick={() => setOpen((v) => !v)}>
        i
      </button>
      {open ? (
        <span id={id} role="note" class="cc-tip-pop">
          {text}
        </span>
      ) : null}
    </span>
  );
}
