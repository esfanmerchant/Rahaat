import { useEffect } from 'preact/hooks';
import { audioUnlocked, playingKey, playPrompt, stopAudio, unlockAudio } from '../audio';
import { lang, t, type MessageKey } from '../i18n';
import { Pictogram } from './Pictogram';

interface AudioPromptProps {
  /** Message key. Plays /audio/{lang}/{prompt}.mp3; the text is t(prompt). */
  prompt: MessageKey;
  /** Play once when the screen opens (only after the first tap unlocked audio). */
  autoPlay?: boolean;
  class?: string;
}

/**
 * The speaker button every citizen screen has. Tap to hear the prompt again,
 * tap while it plays to stop. A missing audio file fails silently.
 */
export function AudioPrompt({ prompt, autoPlay = false, class: className = '' }: AudioPromptProps) {
  const code = lang.value;
  const playing = playingKey.value === prompt;

  useEffect(() => {
    if (autoPlay && audioUnlocked.peek()) playPrompt(prompt, code, t(prompt, undefined, code));
    return () => {
      if (playingKey.peek() === prompt) stopAudio();
    };
  }, [prompt, code, autoPlay]);

  const onClick = (): void => {
    unlockAudio();
    if (playing) stopAudio();
    else playPrompt(prompt, code, t(prompt, undefined, code));
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={playing}
      aria-label={t('listen')}
      class={
        'inline-flex min-h-tap min-w-tap items-center justify-center gap-2 rounded-full border-2 px-3 font-semibold ' +
        (playing
          ? 'border-primary bg-primary text-white'
          : 'border-primary bg-paper text-primary-strong hover:bg-primary-soft') +
        ` ${className}`
      }
    >
      <Pictogram name="speaker" size={32} />
      <span class="text-base" aria-hidden="true">
        {t('listen')}
      </span>
    </button>
  );
}
