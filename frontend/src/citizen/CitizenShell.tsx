import type { ComponentChildren } from 'preact';
import { AudioPrompt, type Speech } from '../shared/components/AudioPrompt';
import { Pictogram } from '../shared/components/Pictogram';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { t, type Key } from '../shared/i18n';
import { useDesktop } from '../shared/useMedia';
import { ActingBanner } from './ActingBanner';
import { ContextPane, type PaneSpec } from './ContextPane';

interface CitizenShellProps {
  /** Shows the back button at the start side of the top bar. */
  onBack?: (() => void) | undefined;
  /** The screen's spoken prompt; the speaker button sits at the end side of the top bar. */
  prompt?: Key | undefined;
  /** A spoken sequence instead of one prompt (review, result). */
  speech?: Speech | undefined;
  autoPlay?: boolean;
  /** Shown under the top bar, for example the progress dots. */
  progress?: ComponentChildren;
  /** A night band at the top on phones and tablets (home); plain page content on a laptop, where the left pane has it. */
  hero?: ComponentChildren;
  /** What the left pane shows on a laptop: the journey (default) or the apply questions. */
  pane?: PaneSpec;
  /** `card` (default): on a laptop the content sits in one raised card. `bare`: the screen draws its own cards. */
  surface?: 'card' | 'bare';
  children?: ComponentChildren;
}

/** One column width everywhere: phone width on phones, 40rem from tablets up. */
const COLUMN = 'mx-auto w-full max-w-phone md:max-w-[40rem]';

/**
 * Citizen layout. Phone (under 768 px): one column, back at the start side, speaker at the end side (both flip
 * in RTL), one question and one primary action below. Tablet: the same, in a 40rem column. Laptop (1024 px and
 * up): two panes. The left is the person's context on the night sky and stays in place; the right is ivory with
 * a faint lattice, and the content sits centred in a raised card.
 */
export function CitizenShell({ onBack, prompt, speech, autoPlay = true, progress, hero, pane = { kind: 'journey' }, surface = 'card', children }: CitizenShellProps) {
  const desktop = useDesktop();
  const night = hero !== undefined && !desktop;
  const header = (
    <header class={`${COLUMN} flex flex-col gap-2 px-4 pt-3 lg:px-8 lg:pt-8`}>
      <div class="flex items-center justify-between gap-3">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            class={
              'inline-flex min-h-tap min-w-tap items-center gap-2 rounded-full border-2 px-3 text-base font-semibold ' +
              (night ? 'border-night-line bg-night-2 text-night-ink hover:bg-night-3' : 'border-line-strong bg-paper text-ink hover:bg-surface')
            }
          >
            <Pictogram name="back" size={28} />
            <span>{t('back')}</span>
          </button>
        ) : (
          <span />
        )}
        {speech || prompt ? <AudioPrompt prompt={prompt} speech={speech} autoPlay={autoPlay} tone={night ? 'night' : 'paper'} /> : null}
      </div>
      {progress ? <div class="lg:hidden">{progress}</div> : null}
    </header>
  );
  return (
    <div class="min-h-dvh bg-paper text-ink lg:grid lg:grid-cols-[2fr_3fr]">
      {desktop ? <ContextPane spec={pane} /> : null}
      <div class="rh-lattice-faint flex min-h-dvh min-w-0 flex-col">
        <ActingBanner />
        {hero !== undefined ? (
          <div class="rh-hero pb-8 lg:pb-0">
            {header}
            <div class={`${COLUMN} px-4 pt-2 lg:px-8`}>{hero}</div>
          </div>
        ) : (
          header
        )}
        <div class="flex flex-1 flex-col lg:justify-center lg:py-8">
          <main
            id="main"
            class={
              `${COLUMN} flex flex-1 flex-col gap-6 px-4 py-4 lg:flex-none ` +
              (surface === 'card' ? 'lg:rounded-2xl lg:border lg:border-line lg:bg-paper lg:p-8 lg:shadow-lift' : 'lg:px-8')
            }
          >
            {children}
          </main>
        </div>
        {desktop ? null : <PrototypeFooter />}
      </div>
    </div>
  );
}
