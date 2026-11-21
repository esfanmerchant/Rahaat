import type { Ref } from 'preact';
import { useEffect } from 'preact/hooks';
import { Emblem } from '../../shared/components/Emblem';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { buzz, celebrate, chime } from '../../shared/feedback';
import { t, type MessageKey } from '../../shared/i18n';

export type VerdictKind = 'approved' | 'needs_proof' | 'needs_human' | 'rejected' | 'pending';

/**
 * "A person will check": a small emblem on the start side, its lamp (a noor dot) travels along a dotted arc to
 * the person-help picture on the end side, which then glows. Nothing is clipped; the arc and the travel mirror
 * in RTL (the CSS reads --rh-dir). Under reduced motion only the final state shows.
 */
function Handover({ big = false }: { big?: boolean }) {
  const box = big ? 'size-24' : 'size-[4.5rem]';
  return (
    <div class="flex w-full max-w-md items-center gap-3" aria-hidden="true">
      <Emblem size={72} tone="night" class={`${box} drop-shadow-glow`} />
      <div class="rh-arc min-w-0 flex-1">
        <svg viewBox="0 0 200 72" preserveAspectRatio="none" class="absolute inset-0 size-full overflow-visible" focusable="false">
          <path d="M0 36Q100 -22 200 36" fill="none" stroke="#a7aed6" stroke-width="2.5" stroke-dasharray="1 8" stroke-linecap="round" vector-effect="non-scaling-stroke" />
        </svg>
        <span class="rh-arc-lamp">
          <span />
        </span>
      </div>
      <span class={`rh-arc-end grid ${box} shrink-0 place-items-center rounded-full border-2 border-night-line bg-night-2 text-noor`}>
        <Pictogram name="person-help" size={big ? 56 : 44} />
      </span>
    </div>
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
      <div class="rh-night-sky relative flex flex-col items-center gap-3 overflow-hidden rounded-2xl px-4 py-8 text-center shadow-glow lg:gap-5 lg:py-14">
        <div aria-hidden="true" class="rh-lattice-night absolute inset-0" />
        <div class="relative grid place-items-center">
          <span aria-hidden="true" class="rh-lampglow absolute size-60 rounded-full bg-noor/25 blur-md lg:size-80" />
          <span aria-hidden="true" class="absolute size-32 rounded-full border-2 border-noor hidden motion-safe:block motion-safe:animate-ring" />
          <Emblem size={144} tone="night" animate class="relative lg:size-52" />
        </div>
        {heading('relative text-noor lg:text-4xl')}
      </div>
    );
  }
  if (kind === 'needs_proof') {
    return (
      <div class="rh-slide-in flex flex-col items-center gap-3 rounded-2xl border-4 border-warning bg-warning-soft px-4 py-6 text-center text-warning-ink shadow-lift lg:gap-5 lg:py-12">
        <span class="grid size-28 place-items-center rounded-full bg-paper">
          <Pictogram name={FALL.needs_proof.icon} size={72} />
        </span>
        {heading('')}
      </div>
    );
  }
  if (kind === 'needs_human' || kind === 'pending') {
    return (
      <div class="rh-night-sky relative flex flex-col items-center gap-4 overflow-hidden rounded-2xl px-4 py-8 text-center shadow-float lg:gap-6 lg:py-14">
        <div aria-hidden="true" class="rh-lattice-night absolute inset-0" />
        <div class="relative flex w-full justify-center">
          <Handover big />
        </div>
        {heading('relative text-night-ink lg:text-3xl')}
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
