import { signal } from '@preact/signals';
import type { Lang } from './i18n';

/**
 * Fixed audio prompts: /audio/{lang}/{key}.mp3, precached by the service worker.
 *
 * Browsers block sound until the person taps the page, so the start screen's
 * first tap calls unlockAudio(). One shared <audio> element is used for every
 * prompt: iOS only lets an element play later if it was first played from a tap.
 *
 * A missing file never shows an error. Order: the file for the language, the
 * Urdu file for Sindhi (TODO(sd)), a device voice for that language if one
 * exists, otherwise silence.
 */
export const audioUnlocked = signal(false);
/** Key of the prompt that is playing now, or null. */
export const playingKey = signal<string | null>(null);

const AUDIO_FALLBACK: Partial<Record<Lang, Lang>> = { sd: 'ur' };

let element: HTMLAudioElement | null = null;
let ticket = 0;

function player(): HTMLAudioElement | null {
  if (typeof Audio === 'undefined') return null;
  if (!element) {
    element = new Audio();
    element.preload = 'auto';
    element.addEventListener('ended', () => {
      playingKey.value = null;
    });
  }
  return element;
}

/** Call from the first tap handler (synchronously, inside the event). */
export function unlockAudio(): void {
  if (audioUnlocked.peek()) return;
  audioUnlocked.value = true;
  const audio = player();
  if (!audio) return;
  audio.src = '/audio/silence.mp3';
  audio.play().catch(() => {
    // A newer prompt replaced the silence, or the browser refused: both are fine.
  });
}

export function stopAudio(): void {
  ticket += 1;
  element?.pause();
  if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
  playingKey.value = null;
}

/**
 * Play the prompt for `key` in `code`. `spokenText` is what the recording says;
 * it is only used for the device-voice fallback.
 */
export function playPrompt(key: string, code: Lang, spokenText?: string): void {
  const audio = player();
  if (!audio) return;
  stopAudio();
  const mine = ticket;

  const attempt = (fileLang: Lang): void => {
    audio.src = `/audio/${fileLang}/${key}.mp3`;
    playingKey.value = key;
    audio.play().catch((error: unknown) => {
      if (mine !== ticket) return; // replaced by a newer prompt
      const name = error instanceof DOMException ? error.name : '';
      if (name === 'NotAllowedError' || name === 'AbortError') {
        playingKey.value = null; // not unlocked yet, or interrupted
        return;
      }
      const next = AUDIO_FALLBACK[fileLang];
      if (next) {
        attempt(next);
        return;
      }
      if (!speak(spokenText, fileLang, mine)) playingKey.value = null;
    });
  };
  attempt(code);
}

function speak(text: string | undefined, code: Lang, mine: number): boolean {
  if (!text || typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance === 'undefined') {
    return false;
  }
  // Only a voice that really speaks this language; never read Urdu with an English voice.
  const voice = speechSynthesis
    .getVoices()
    .find((candidate) => candidate.lang.toLowerCase().replace('_', '-').startsWith(code));
  if (!voice) return false;
  const utterance = new SpeechSynthesisUtterance(text.replace(/[⁦-⁩]/g, ''));
  utterance.voice = voice;
  utterance.lang = voice.lang;
  const done = (): void => {
    if (mine === ticket) playingKey.value = null;
  };
  utterance.onend = done;
  utterance.onerror = done;
  speechSynthesis.speak(utterance);
  return true;
}
