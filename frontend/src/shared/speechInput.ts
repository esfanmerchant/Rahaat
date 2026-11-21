import { useEffect, useRef, useState } from 'preact/hooks';
import type { Lang } from './i18n';

/**
 * Speech to text with the phone's own recognition (Web Speech API), where it
 * exists. Nothing is sent by this app: the browser runs it. The caller always
 * reads the result back and asks the person to confirm it with an icon, and
 * pictogram or paste input stays available when this is missing or refused.
 */
interface RecognitionResultList {
  readonly length: number;
  [index: number]: { readonly isFinal: boolean; readonly length: number; [index: number]: { readonly transcript: string } };
}
interface RecognitionEvent {
  readonly results: RecognitionResultList;
}
interface RecognitionError {
  readonly error: string;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionError) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

/** Recognition locales: Pakistani Urdu, and the South Asian English the voices use. */
const LOCALES: Record<Lang, string> = { ur: 'ur-PK', en: 'en-IN' };

function ctor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechInputAvailable(): boolean {
  return ctor() !== null;
}

export type SpeechInput =
  | { state: 'idle' }
  | { state: 'listening'; partial: string }
  | { state: 'heard'; text: string }
  /** denied: microphone permission refused. unavailable: no recognition or no microphone. nothing: no speech heard. */
  | { state: 'failed'; why: 'denied' | 'unavailable' | 'nothing' | 'failed' };

const DENIED = new Set(['not-allowed', 'service-not-allowed']);
const UNAVAILABLE = new Set(['audio-capture', 'language-not-supported', 'bad-grammar']);

/** Listen once in `code`. Returns the state and start / stop / reset. */
export function useSpeechInput(code: Lang) {
  const [input, setInput] = useState<SpeechInput>({ state: 'idle' });
  const active = useRef<Recognition | null>(null);

  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );

  const start = (): void => {
    const Ctor = ctor();
    if (!Ctor) {
      setInput({ state: 'failed', why: 'unavailable' });
      return;
    }
    active.current?.abort();
    let recognition: Recognition;
    try {
      recognition = new Ctor();
    } catch {
      setInput({ state: 'failed', why: 'unavailable' });
      return;
    }
    let finalText = '';
    let partial = '';
    let failed: SpeechInput | null = null;
    recognition.lang = LOCALES[code];
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      finalText = '';
      partial = '';
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        const best = result?.[0]?.transcript ?? '';
        if (result?.isFinal) finalText += best;
        else partial += best;
      }
      setInput({ state: 'listening', partial: `${finalText}${partial}`.trim() });
    };
    recognition.onerror = (event) => {
      const why = DENIED.has(event.error)
        ? 'denied'
        : UNAVAILABLE.has(event.error)
          ? 'unavailable'
          : event.error === 'no-speech' || event.error === 'aborted'
            ? 'nothing'
            : 'failed';
      failed = { state: 'failed', why };
    };
    recognition.onend = () => {
      if (active.current !== recognition) return;
      active.current = null;
      const text = (finalText || partial).trim();
      if (text) setInput({ state: 'heard', text });
      else setInput(failed ?? { state: 'failed', why: 'nothing' });
    };
    active.current = recognition;
    setInput({ state: 'listening', partial: '' });
    try {
      recognition.start();
    } catch {
      active.current = null;
      setInput({ state: 'failed', why: 'failed' });
    }
  };

  /** Stop listening and keep what was heard so far. */
  const stop = (): void => active.current?.stop();

  const reset = (): void => {
    active.current?.abort();
    active.current = null;
    setInput({ state: 'idle' });
  };

  return { input, start, stop, reset };
}
