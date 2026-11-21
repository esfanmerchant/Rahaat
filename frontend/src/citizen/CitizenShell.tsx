import type { ComponentChildren } from 'preact';
import { AudioPrompt, type Speech } from '../shared/components/AudioPrompt';
import { Pictogram } from '../shared/components/Pictogram';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { t, type Key } from '../shared/i18n';
import { ActingBanner } from './ActingBanner';

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
  children?: ComponentChildren;
}

/**
 * Citizen layout: one phone-width column, back at the start side, speaker at
 * the end side (both flip in RTL), one question and one primary action below.
 */
export function CitizenShell({ onBack, prompt, speech, autoPlay = true, progress, children }: CitizenShellProps) {
  return (
    <div class="flex min-h-dvh flex-col bg-paper text-ink">
      <ActingBanner />
      <header class="mx-auto flex w-full max-w-phone flex-col gap-2 px-4 pt-3">
        <div class="flex items-center justify-between gap-3">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              class="inline-flex min-h-tap min-w-tap items-center gap-2 rounded-full border-2 border-line-strong bg-paper px-3 text-base font-semibold text-ink hover:bg-surface"
            >
              <Pictogram name="back" size={28} />
              <span>{t('back')}</span>
            </button>
          ) : (
            <span />
          )}
          {speech || prompt ? <AudioPrompt prompt={prompt} speech={speech} autoPlay={autoPlay} /> : null}
        </div>
        {progress}
      </header>
      <main id="main" class="mx-auto flex w-full max-w-phone flex-1 flex-col gap-6 px-4 py-4">
        {children}
      </main>
      <PrototypeFooter />
    </div>
  );
}
