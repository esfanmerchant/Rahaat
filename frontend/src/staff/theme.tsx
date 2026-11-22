import type { ComponentChildren } from 'preact';
import { useEffect } from 'preact/hooks';
import { signal } from '@preact/signals';
import './staff.css';
import './shell.css';
import './calm.css';

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

type VT = { finished: Promise<void> };
type DocVT = Document & { startViewTransition?: (cb: () => Promise<void> | void) => VT };

/**
 * Night/day switch. With the View Transitions API the new theme is revealed in a circle growing from the toggle button
 * (shell.css animates ::view-transition-new(root) while html carries .st-theme-vt). Without it, colours cross-fade
 * (.st-theme-fade). Reduced motion: instant. The DOM theme attribute is set inside the transition callback so the
 * snapshot taken afterwards already shows the new theme.
 */
export function toggleTheme(origin?: unknown): void {
  const next: Theme = theme.value === 'night' ? 'day' : 'night';
  const html = document.documentElement;
  const apply = (): void => {
    html.dataset['theme'] = next;
    document.querySelectorAll<HTMLElement>('.st-root').forEach((el) => {
      el.dataset['theme'] = next;
    });
    setTheme(next);
  };
  const el = origin instanceof Event ? (origin.currentTarget as HTMLElement | null) : origin instanceof HTMLElement ? origin : null;
  const doc = document as DocVT;
  if (prefersReducedMotion()) {
    apply();
    return;
  }
  if (typeof doc.startViewTransition !== 'function') {
    html.classList.add('st-theme-fade');
    apply();
    window.setTimeout(() => html.classList.remove('st-theme-fade'), 500);
    return;
  }
  const r = el?.getBoundingClientRect();
  const x = r ? r.left + r.width / 2 : window.innerWidth / 2;
  const y = r ? r.top + r.height / 2 : 0;
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  html.style.setProperty('--st-vt-x', `${x}px`);
  html.style.setProperty('--st-vt-y', `${y}px`);
  html.style.setProperty('--st-vt-r', `${Math.ceil(radius)}px`);
  html.classList.add('st-theme-vt');
  const vt = doc.startViewTransition(
    () =>
      new Promise<void>((resolve) => {
        apply();
        requestAnimationFrame(() => window.setTimeout(resolve, 0)); // let Preact paint the new theme before the snapshot
      }),
  );
  void vt.finished.finally(() => html.classList.remove('st-theme-vt'));
}

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
