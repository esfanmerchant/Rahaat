import { t, type MessageKey } from '../shared/i18n';

export type StarState = 'done' | 'current' | 'next';

/** An eight-point star on a night surface: lamp gold when finished (with a tick), a pulsing lamp when current, an outline when next. */
export function NightStar({ state, size = 44 }: { state: StarState; size?: number }) {
  return (
    <span class="relative grid shrink-0 place-items-center" style={{ width: `${size}px`, height: `${size}px` }}>
      {state === 'current' ? <span aria-hidden="true" class="absolute inset-0 rounded-full bg-noor/30 hidden motion-safe:block motion-safe:animate-ring" /> : null}
      <svg viewBox="0 0 48 48" width={size} height={size} aria-hidden="true" class={state === 'done' ? 'drop-shadow-glow' : ''}>
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

export interface PathItem {
  key: string;
  label: MessageKey;
}

/**
 * A vertical star path for a night surface (the left pane of the laptop layout): one star per step, joined by a
 * line that is lit up to the current step. `done` is how many steps are finished; the next one is current.
 */
export function StarPath({ items, done, title, compact = false, stopped = false }: { items: readonly PathItem[]; done: number; title: MessageKey; compact?: boolean; stopped?: boolean }) {
  const size = compact ? 32 : 44;
  return (
    <section aria-label={t(title)} class="flex flex-col gap-3">
      <h2 class="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-night-muted">
        <StarBullet />
        {t(title)}
      </h2>
      <ol class="flex flex-col">
        {items.map((item, index) => {
          const state: StarState = index < done ? 'done' : index === done && !stopped ? 'current' : 'next';
          const last = index === items.length - 1;
          return (
            <li key={item.key} aria-current={state === 'current' ? 'step' : undefined} class="flex items-stretch gap-4">
              <div class="flex flex-col items-center">
                <NightStar state={state} size={size} />
                {last ? null : <span aria-hidden="true" class={`w-0.5 flex-1 ${index < done ? 'bg-noor' : 'bg-night-line'} ${compact ? 'min-h-1.5' : 'min-h-3'}`} />}
              </div>
              <span
                class={`flex items-center ${last ? '' : compact ? 'pb-1.5' : 'pb-3'} ${compact ? 'text-base' : 'text-xl'} font-semibold ${state === 'next' ? 'text-night-muted' : state === 'current' ? 'text-noor' : 'text-night-ink'}`}
              >
                {t(item.label)}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** A small eight-point star bullet for section headers. */
export function StarBullet({ class: className = '' }: { class?: string }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" class={`shrink-0 ${className}`}>
      <g fill="currentColor">
        <rect x="6" y="6" width="12" height="12" />
        <rect x="6" y="6" width="12" height="12" transform="rotate(45 12 12)" />
      </g>
    </svg>
  );
}
