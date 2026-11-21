import type { ComponentChildren } from 'preact';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Pictogram } from '../shared/components/Pictogram';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { t, type MessageKey } from '../shared/i18n';

interface CitizenShellProps {
  /** Shows the back button at the start side of the top bar. */
  onBack?: () => void;
  /** The screen's spoken prompt; the speaker button sits at the end side of the top bar. */
  prompt?: MessageKey;
  autoPlay?: boolean;
  children?: ComponentChildren;
}

/**
 * Citizen layout: one phone-width column, back at the start side, speaker at
 * the end side (both flip in RTL), one question and one primary action below.
 */
export function CitizenShell({ onBack, prompt, autoPlay = true, children }: CitizenShellProps) {
  return (
    <div class="flex min-h-dvh flex-col bg-paper text-ink">
      <header class="mx-auto flex w-full max-w-phone items-center justify-between gap-3 px-4 pt-3">
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
        {prompt ? <AudioPrompt prompt={prompt} autoPlay={autoPlay} /> : null}
      </header>
      <main id="main" class="mx-auto flex w-full max-w-phone flex-1 flex-col gap-6 px-4 py-4">
        {children}
      </main>
      <PrototypeFooter />
    </div>
  );
}
