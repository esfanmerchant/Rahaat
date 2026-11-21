import type { Ref } from 'preact';
import { useEffect } from 'preact/hooks';
import { Emblem } from '../../shared/components/Emblem';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { buzz, celebrate, chime } from '../../shared/feedback';
import { t, type MessageKey } from '../../shared/i18n';

export type VerdictKind = 'approved' | 'needs_proof' | 'needs_human' | 'rejected' | 'pending';

/** The lamp handed from one hand to another: "a person will check". Two cupped hands, a lamp that crosses between them. */
function Handover() {
  return (
    <svg viewBox="0 0 200 120" width="200" height="120" class="max-w-full overflow-visible" aria-hidden="true" focusable="false">
      <g fill="#1b2552" stroke="#8ea2ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
        <path d="M0 98H62Q88 98 96 74Q98 70 93 70Q86 70 83 80Q80 88 62 88H0z" />
        <path d="M200 98H138Q112 98 104 74Q102 70 107 70Q114 70 117 80Q120 88 138 88H200z" />
      </g>
      <g class="rh-handover">
        <circle cx="64" cy="58" r="26" fill="#ffd36e" opacity=".22" />
        <path d="M54 76h20l-3 7H57z" fill="#ffd36e" />
        <path d="M64 44c7 7 9 12 4 18-2 2-6 2-8 0-5-6-3-11 4-18z" fill="#ffd36e" />
      </g>
    </svg>
  );
}

const FALL: Record<Exclude<VerdictKind, 'approved' | 'needs_human' | 'pending'>, { icon: PictogramName }> = {
  needs_proof: { icon: 'document' },
  rejected: { icon: 'no' },
};

/**
 * The top of the result screen, choreographed by outcome with the existing keyed sentences only.
 * approved: the lamp lights, the homes glow one by one, then the chime and a short buzz.
 * needs_proof: a saffron card slides in. needs_human / pending: the lamp is handed over. rejected: calm.
 * Reduced motion: the global rule makes every animation land on its end state at once.
 */
export function Verdict({ kind, title, icon, headingRef }: { kind: VerdictKind; title: MessageKey; icon: PictogramName; headingRef: Ref<HTMLHeadingElement> }) {
  useEffect(() => {
    if (kind === 'approved') {
      const id = window.setTimeout(celebrate, 1700);
      return () => window.clearTimeout(id);
    }
    if (kind === 'needs_proof') {
      const id = window.setTimeout(() => {
        chime('warn');
        buzz(40);
      }, 500);
      return () => window.clearTimeout(id);
    }
    if (kind === 'needs_human' || kind === 'pending') {
      const id = window.setTimeout(() => chime('soft'), 2300);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [kind]);

  const heading = (cls: string) => (
    <h1 ref={headingRef} tabIndex={-1} class={`text-2xl font-extrabold ${cls}`}>
      {t(title)}
    </h1>
  );

  if (kind === 'approved') {
    return (
      <div class="rh-night-sky relative flex flex-col items-center gap-3 overflow-hidden rounded-2xl px-4 py-8 text-center shadow-glow">
        <div aria-hidden="true" class="rh-lattice-night absolute inset-0" />
        <div class="relative grid place-items-center">
          <span aria-hidden="true" class="rh-lampglow absolute size-60 rounded-full bg-noor/25 blur-md" />
          <span aria-hidden="true" class="absolute size-32 rounded-full border-2 border-noor hidden motion-safe:block motion-safe:animate-ring" />
          <Emblem size={144} tone="night" animate class="relative" />
        </div>
        {heading('relative text-noor')}
      </div>
    );
  }
  if (kind === 'needs_proof') {
    return (
      <div class="rh-slide-in flex flex-col items-center gap-3 rounded-2xl border-4 border-warning bg-warning-soft px-4 py-6 text-center text-warning-ink shadow-lift">
        <span class="grid size-28 place-items-center rounded-full bg-paper">
          <Pictogram name={FALL.needs_proof.icon} size={72} />
        </span>
        {heading('')}
      </div>
    );
  }
  if (kind === 'needs_human' || kind === 'pending') {
    return (
      <div class="rh-night-sky flex flex-col items-center gap-2 rounded-2xl px-4 py-6 text-center shadow-float">
        <Handover />
        {heading('text-night-ink')}
      </div>
    );
  }
  return (
    <div class="motion-safe:animate-fade flex flex-col items-center gap-3 rounded-2xl border-2 border-line-strong bg-surface px-4 py-6 text-center">
      <span class="grid size-24 place-items-center rounded-full border-4 border-line-strong bg-paper text-ink-muted">
        <Pictogram name={icon} size={56} />
      </span>
      {heading('')}
    </div>
  );
}
