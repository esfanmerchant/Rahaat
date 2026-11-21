import { signal } from '@preact/signals';
import { getPref, setPref } from './prefs';

/**
 * Sound and touch for the moments that matter (a decision, a payment, the scam verdict): a soft bell made
 * with Web Audio (a few sine partials, exponential decay; no audio files) and a short vibration.
 * Both stop when the person turns sound off (stored with the device preferences) and the vibration also
 * stops under reduced motion. Nothing here ever throws or blocks.
 */
export const soundOn = signal(true);

void getPref('muted').then((value) => {
  if (value === true) soundOn.value = false;
});

export function setSound(on: boolean): void {
  soundOn.value = on;
  void setPref('muted', !on);
  if (on) chime('soft');
}

let ctx: AudioContext | null = null;

function context(): AudioContext | null {
  if (ctx) return ctx;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (Ctor) ctx = new Ctor();
  } catch {
    ctx = null;
  }
  return ctx;
}

/** Bell partials: ratio to the fundamental, relative loudness, decay seconds. */
const PARTIALS: ReadonlyArray<readonly [number, number, number]> = [
  [1, 1, 1.6],
  [2.01, 0.45, 1.1],
  [3.02, 0.22, 0.7],
  [4.97, 0.1, 0.4],
];

/** `bright` is the good-news chime (two notes, a fifth apart); `soft` a single low bell; `warn` a single lower, shorter one. */
export type ChimeKind = 'bright' | 'soft' | 'warn';

const NOTES: Record<ChimeKind, readonly number[]> = { bright: [659.25, 987.77], soft: [523.25], warn: [392] };

export function chime(kind: ChimeKind = 'bright'): void {
  if (!soundOn.value) return;
  const ac = context();
  if (!ac) return;
  try {
    void ac.resume();
    const start = ac.currentTime + 0.02;
    NOTES[kind].forEach((freq, n) => {
      const at = start + n * 0.16;
      for (const [ratio, gain, decay] of PARTIALS) {
        const osc = ac.createOscillator();
        const amp = ac.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq * ratio;
        const peak = 0.12 * gain;
        amp.gain.setValueAtTime(0.0001, at);
        amp.gain.exponentialRampToValueAtTime(peak, at + 0.012);
        amp.gain.exponentialRampToValueAtTime(0.0001, at + decay);
        osc.connect(amp).connect(ac.destination);
        osc.start(at);
        osc.stop(at + decay + 0.05);
      }
    });
  } catch {
    // Sound is a bonus; never an error.
  }
}

export function buzz(pattern: number | number[] = 40): void {
  if (!soundOn.value) return;
  try {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    navigator.vibrate?.(pattern);
  } catch {
    // ignore
  }
}

/** The good-news moment: bell, then a short double tap. */
export function celebrate(): void {
  chime('bright');
  buzz([30, 60, 50]);
}
