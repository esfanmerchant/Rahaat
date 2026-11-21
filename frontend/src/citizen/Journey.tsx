import type { ApplicationStatus } from '../shared/api/types';
import { t, type MessageKey } from '../shared/i18n';

/**
 * The application journey: sent, checked, decided, paid. Each step is an eight-point star on a night card.
 * Finished steps glow lamp gold, the current one pulses gently, the next ones are outlined.
 */
const STEPS: readonly { key: MessageKey }[] = [
  { key: 'journey_sent' },
  { key: 'journey_checked' },
  { key: 'journey_decided' },
  { key: 'journey_paid' },
];

/** How many steps are finished for a status (null: no application yet). */
export function stepsDone(status: ApplicationStatus | null): number {
  switch (status) {
    case null:
    case 'draft':
    case 'withdrawn':
      return 0;
    case 'submitted':
    case 'needs_proof':
    case 'in_review':
    case 'on_hold_consent':
      return 1;
    case 'approved':
    case 'rejected':
      return 3;
    case 'paid':
      return 4;
  }
}

function Star({ state }: { state: 'done' | 'current' | 'next' }) {
  return (
    <span class="relative grid size-12 place-items-center">
      {state === 'current' ? <span aria-hidden="true" class="absolute inset-0 rounded-full bg-noor/30 hidden motion-safe:block motion-safe:animate-ring" /> : null}
      <svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" class={state === 'done' ? 'drop-shadow-glow' : ''}>
        <g
          fill={state === 'done' ? '#ffd36e' : 'none'}
          stroke={state === 'next' ? '#a7aed6' : '#ffd36e'}
          stroke-width={state === 'next' ? 2 : 2.5}
          stroke-linejoin="round"
        >
          <rect x="10" y="10" width="28" height="28" />
          <rect x="10" y="10" width="28" height="28" transform="rotate(45 24 24)" />
        </g>
        {state === 'done' ? <path d="M17 24.5l5 5 9-10" fill="none" stroke="#070b1d" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /> : null}
        {state === 'current' ? <circle cx="24" cy="24" r="5" fill="#ffd36e" class="motion-safe:animate-twinkle" /> : null}
      </svg>
    </span>
  );
}

export function Journey({ status }: { status: ApplicationStatus | null }) {
  const done = stepsDone(status);
  const stopped = status === 'rejected' || status === 'withdrawn';
  return (
    <section class="rh-night-sky rounded-2xl px-4 py-5 shadow-float" aria-label={t('journey_title')}>
      <h2 class="mb-3 text-base font-semibold text-night-muted">{t('journey_title')}</h2>
      <ol class="flex items-start">
        {STEPS.map((step, index) => {
          const state = index < done ? 'done' : index === done && !stopped ? 'current' : 'next';
          return (
            <li key={step.key} class="flex flex-1 flex-col items-center gap-1" aria-current={state === 'current' ? 'step' : undefined}>
              <div class="flex w-full items-center">
                <span aria-hidden="true" class={`h-0.5 flex-1 ${index === 0 ? 'opacity-0' : index <= done ? 'bg-noor' : 'bg-night-line'}`} />
                <Star state={state} />
                <span aria-hidden="true" class={`h-0.5 flex-1 ${index === STEPS.length - 1 ? 'opacity-0' : index < done ? 'bg-noor' : 'bg-night-line'}`} />
              </div>
              <span class={`text-center text-sm font-semibold ${state === 'next' ? 'text-night-muted' : 'text-night-ink'}`}>{t(step.key)}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
