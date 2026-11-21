import { computed, effect, signal } from '@preact/signals';
import { useLayoutEffect } from 'preact/hooks';
import { getPref, setPref } from '../prefs';
import { en, type Dict, type MessageKey } from './en';
import { sd } from './sd';
import { ur } from './ur';

export type { MessageKey } from './en';

export type Lang = 'ur' | 'sd' | 'en';
export type Dir = 'rtl' | 'ltr';

export interface LangInfo {
  readonly code: Lang;
  /** The language's own name, shown on the language buttons. */
  readonly native: string;
  readonly dir: Dir;
}

export const LANGUAGES: readonly LangInfo[] = [
  { code: 'ur', native: 'اردو', dir: 'rtl' },
  { code: 'sd', native: 'سنڌي', dir: 'rtl' },
  { code: 'en', native: 'English', dir: 'ltr' },
];

export const DEFAULT_LANG: Lang = 'ur';

const DICTS: Record<Lang, Partial<Dict>> = { en, ur, sd };

/** Lookup order for a missing key. TODO(sd): drop the Urdu fallback once Sindhi is complete. */
const FALLBACK: Record<Lang, readonly Lang[]> = {
  ur: ['ur', 'en'],
  sd: ['sd', 'ur', 'en'],
  en: ['en'],
};

/** The current UI language. Reading `.value` in a component subscribes it. */
export const lang = signal<Lang>(DEFAULT_LANG);
export const dir = computed<Dir>(() => dirOf(lang.value));

let chosenOnThisDevice = false;

export function isLang(value: unknown): value is Lang {
  return value === 'ur' || value === 'sd' || value === 'en';
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

/** Translate a key. Interpolates `{name}` placeholders, each bidi-isolated. */
export function t(key: MessageKey, params?: Params, code: Lang = lang.value): string {
  let text: string | undefined;
  for (const candidate of FALLBACK[code]) {
    text = DICTS[candidate][key];
    if (text !== undefined) break;
  }
  const template = text ?? key;
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
export function useTemporaryLang(code: Lang): void {
  useLayoutEffect(() => {
    const previous = lang.peek();
    setLang(code, { persist: false });
    return () => setLang(previous, { persist: false });
  }, [code]);
}

// Keep <html lang dir> in step with the language. Logical CSS properties
// (ms-, pe-, start-, text-start) then flip the layout on their own.
effect(() => {
  const root = document.documentElement;
  root.lang = lang.value;
  root.dir = dirOf(lang.value);
});
