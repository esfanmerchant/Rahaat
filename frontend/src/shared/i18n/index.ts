import { computed, effect, signal } from '@preact/signals';
import { useLayoutEffect } from 'preact/hooks';
import { getPref, setPref } from '../prefs';
import { en, type Dict, type MessageKey } from './en';
import { ur } from './ur';

import type { MoreKey } from './more.en';

export type { MessageKey } from './en';
/** Keys of the main dictionary plus the lazy ones (more.en.ts), which load with their chunk. */
export type Key = MessageKey | MoreKey;

/** Urdu (default) and English. Sindhi was dropped: nobody on the team can proofread it (docs/DESIGN.md). */
export type Lang = 'ur' | 'en';
export type Dir = 'rtl' | 'ltr';

export interface LangInfo {
  readonly code: Lang;
  /** The language's own name, shown on the language buttons. */
  readonly native: string;
  readonly dir: Dir;
}

export const LANGUAGES: readonly LangInfo[] = [
  { code: 'ur', native: 'اردو', dir: 'rtl' },
  { code: 'en', native: 'English', dir: 'ltr' },
];

export const DEFAULT_LANG: Lang = 'ur';

const DICTS: Record<Lang, Dict> = { en, ur };
const MORE: Record<Lang, Readonly<Record<string, string>>> = { en: {}, ur: {} };

/** A lazy chunk adds its own strings (imported through ./more for its side effect). */
export function registerStrings(enMore: Readonly<Record<string, string>>, urMore: Readonly<Record<string, string>>): void {
  MORE.en = enMore;
  MORE.ur = urMore;
}

/** The current UI language. Reading `.value` in a component subscribes it. */
export const lang = signal<Lang>(DEFAULT_LANG);
export const dir = computed<Dir>(() => dirOf(lang.value));

let chosenOnThisDevice = false;

export function isLang(value: unknown): value is Lang {
  return value === 'ur' || value === 'en';
}

export function dirOf(code: Lang): Dir {
  return code === 'en' ? 'ltr' : 'rtl';
}

// Unicode first-strong isolate / pop directional isolate. Wrapping every
// interpolated value keeps names and numbers from scrambling the sentence
// around them when the directions differ (an English name in Urdu text).
const FSI = '⁨';
const PDI = '⁩';

export type Params = Readonly<Record<string, string | number>>;

/**
 * True when `key` is one of our message keys. Server responses name keys
 * (`message_key`, `label_key`, audio keys); only known keys are shown, so the
 * server can never put arbitrary text on a citizen screen through a key.
 */
export function isMessageKey(key: string): key is MessageKey {
  return Object.prototype.hasOwnProperty.call(en, key);
}

/** Server keys use dots (`timeline.submitted`); ours use underscores. */
export function messageKeyFor(serverKey: string | null | undefined): MessageKey | null {
  if (!serverKey) return null;
  const local = serverKey.replace(/[.-]/g, '_');
  return isMessageKey(local) ? local : null;
}

/** Translate a key. Interpolates `{name}` placeholders, each bidi-isolated. */
export function t(key: Key, params?: Params, code: Lang = lang.value): string {
  const template = (DICTS[code] as Readonly<Record<string, string>>)[key] ?? MORE[code][key] ?? (en as Record<string, string>)[key] ?? MORE.en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name];
    return value === undefined ? match : `${FSI}${value}${PDI}`;
  });
}

/**
 * Change the UI language. `persist: false` is for temporary switches (the
 * staff console runs in English) and for the language stored on the profile.
 */
export function setLang(next: Lang, options: { persist?: boolean } = {}): void {
  lang.value = next;
  if (options.persist !== false) {
    chosenOnThisDevice = true;
    void setPref('lang', next);
  }
}

/** True when the person picked a language on this device (it then wins over the profile). */
export function hasChosenLang(): boolean {
  return chosenOnThisDevice;
}

/** Load the saved language before the first render, so the first paint is in the right script. */
export async function initLang(): Promise<void> {
  const saved = await getPref('lang');
  if (isLang(saved)) {
    lang.value = saved;
    chosenOnThisDevice = true;
  }
}

/**
 * Run an area in a fixed language while it is mounted, then restore the
 * person's language. The staff console and /demo use this for English.
 */
// How many mounted areas hold a fixed language. A route can mount before the old one unmounts
// (/demo -> /staff), so only the last one to leave restores the person's language. Every holder uses English.
let holds = 0;
let outside: Lang = DEFAULT_LANG;

export function useTemporaryLang(code: Lang): void {
  useLayoutEffect(() => {
    if (!holds++) outside = lang.peek();
    setLang(code, { persist: false });
    return () => {
      if (!--holds) setLang(outside, { persist: false });
    };
  }, [code]);
}

// Keep <html lang dir> in step with the language. Logical CSS properties
// (ms-, pe-, start-, text-start) then flip the layout on their own.
effect(() => {
  const root = document.documentElement;
  root.lang = lang.value;
  root.dir = dirOf(lang.value);
});
