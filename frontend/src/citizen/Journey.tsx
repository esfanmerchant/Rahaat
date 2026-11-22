import type { ApplicationStatus } from '../shared/api/types';
import { t, type MessageKey } from '../shared/i18n';
import { NightStar } from './JourneyPath';

/**
 * The application journey: sent, checked, decided, paid. Each step is an eight-point star on a night card.
 * Finished steps glow lamp gold, the current one pulses gently, the next ones are outlined.
 */
export const JOURNEY_STEPS: readonly { key: MessageKey }[] = [
  { key: 'outbox_sent' },
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

export function Journey({ status, bare = false }: { status: ApplicationStatus | null; bare?: boolean }) {
  const done = stepsDone(status);
  const stopped = status === 'rejected' || status === 'withdrawn';
  return (
    <section class={bare ? 'py-1' : 'rh-night-sky rounded-2xl px-4 py-5 shadow-float'} aria-label={t('journey_title')}>
      <h2 class="mb-3 text-base font-semibold text-night-muted">{t('journey_title')}</h2>
      <ol class="flex items-start">
        {JOURNEY_STEPS.map((step, index) => {
          const state = index < done ? 'done' : index === done && !stopped ? 'current' : 'next';
          return (
            <li key={step.key} class="flex flex-1 flex-col items-center gap-1" aria-current={state === 'current' ? 'step' : undefined}>
              <div class="flex w-full items-center">
                <span aria-hidden="true" class={`h-0.5 flex-1 ${index === 0 ? 'opacity-0' : index <= done ? 'bg-noor' : 'bg-night-line'}`} />
                <NightStar state={state} />
                <span aria-hidden="true" class={`h-0.5 flex-1 ${index === JOURNEY_STEPS.length - 1 ? 'opacity-0' : index < done ? 'bg-noor' : 'bg-night-line'}`} />
              </div>
              <span class={`text-center text-sm font-semibold ${state === 'next' ? 'text-night-muted' : 'text-night-ink'}`}>{t(step.key)}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
