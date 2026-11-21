import { useEffect } from 'preact/hooks';
import { audioUnlocked, playingKey, playSpeech, stopAudio, unlockAudio, type SpeechItem } from '../audio';
import { lang, t, type Key, type Lang } from '../i18n';
import { Pictogram } from './Pictogram';

/** A spoken sequence: several clips played in order (review answers, a decision). */
export interface Speech {
  /** Changes whenever the content changes, so auto-play runs again. */
  id: string;
  items: readonly SpeechItem[];
  /** Language of the clips; defaults to the UI language. */
  lang?: Lang;
}

/** The speech for one message key in the current language. */
export function speechFor(key: Key, code: Lang = lang.value): Speech {
  return { id: key, items: [{ key, text: t(key, undefined, code) }], lang: code };
}

interface AudioPromptProps {
  /** Message key. Plays /audio/{lang}/{prompt}.mp3; the text is t(prompt). */
  prompt?: Key;
  /** A sequence instead of one prompt. */
  speech?: Speech;
  /** Play once when the screen opens (only after the first tap unlocked audio). */
  autoPlay?: boolean;
  /** Visible word next to the speaker; defaults to "Listen". */
  label?: string;
  class?: string;
}

/**
 * The speaker button every citizen screen has. Tap to hear the prompt again,
 * tap while it plays to stop. A missing audio file fails silently.
 */
export function AudioPrompt({ prompt, speech, autoPlay = false, label, class: className = '' }: AudioPromptProps) {
  const code = lang.value;
  const resolved: Speech | null = speech ?? (prompt ? speechFor(prompt, code) : null);
  const id = resolved?.id ?? '';
  const playing = resolved !== null && playingKey.value === id;

  useEffect(() => {
    if (!resolved) return undefined;
    if (autoPlay && audioUnlocked.peek()) playSpeech(id, resolved.items, resolved.lang ?? code);
    return () => {
      if (playingKey.peek() === id) stopAudio();
    };
  }, [id, code, autoPlay]);

  if (!resolved) return null;

  const onClick = (): void => {
    unlockAudio();
    if (playing) stopAudio();
    else playSpeech(id, resolved.items, resolved.lang ?? code);
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={playing}
      aria-label={label ?? t('listen')}
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
        {label ?? t('listen')}
      </span>
    </button>
  );
}
