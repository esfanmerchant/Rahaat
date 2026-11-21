import type { ComponentChildren } from 'preact';
import { useEffect } from 'preact/hooks';
import { signal } from '@preact/signals';
import './staff.css';

/** Night is the default; the choice is remembered per browser. Storage can be blocked, so every access is guarded. */
export type Theme = 'night' | 'day';
const KEY = 'rahat.staff.theme';

function read(): Theme {
  try {
    return window.localStorage.getItem(KEY) === 'day' ? 'day' : 'night';
  } catch {
    return 'night';
  }
}

export const theme = signal<Theme>(read());

export function setTheme(next: Theme): void {
  theme.value = next;
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
}

export const toggleTheme = (): void => setTheme(theme.value === 'night' ? 'day' : 'night');

/** The staff root: carries data-theme, paints the page colour, and mirrors the theme on <html> so overscroll matches. */
export function StaffRoot({ children, class: extra = '' }: { children?: ComponentChildren; class?: string }) {
  const t = theme.value;
  useEffect(() => {
    const html = document.documentElement;
    html.dataset['theme'] = t;
    return () => {
      delete html.dataset['theme'];
    };
  }, [t]);
  return (
    <div data-theme={t} class={`st-root flex flex-col text-sm ${extra}`}>
      {children}
    </div>
  );
}

export const prefersReducedMotion = (): boolean => {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
};
