import { signal } from '@preact/signals';
import type { ComponentType } from 'preact';
import { useLayoutEffect } from 'preact/hooks';
import { lazy, useLocation } from 'preact-iso';
import { online } from './network';
import { ScreenState } from './components/ScreenState';

/** True while a lazy route chunk is downloading (drives the top progress bar). */
export const routeLoading = signal(false);

/** Navigate on mount (replacing history), for guards and role-based landing. */
export function Redirect({ to }: { to: string }) {
  const { route } = useLocation();
  useLayoutEffect(() => {
    route(to, true);
  }, [to]);
  return null;
}

function ChunkFailed() {
  // The staff and demo chunks are not precached; offline they cannot load.
  return (
    <main class="mx-auto flex min-h-dvh w-full max-w-phone flex-col px-4">
      <ScreenState kind={online.value ? 'error' : 'offline'} onRetry={() => window.location.reload()} />
    </main>
  );
}

/**
 * preact-iso's lazy() caches a failed import forever and never re-renders, so a
 * chunk that fails to download would leave a blank screen. This wrapper turns
 * the failure into an error or offline state with a reload button.
 */
export function lazyRoute<P>(load: () => Promise<{ default: ComponentType<P> }>): ComponentType<P> {
  return lazy(() =>
    load().catch((error: unknown) => {
      console.error('Route chunk failed to load', error);
      return { default: ChunkFailed as ComponentType<P> };
    }),
  );
}

type Navigate = (url: string, replace?: boolean) => void;

/**
 * Navigate with a view transition where the browser has one (a slide in the reading direction: left in
 * Urdu, right in English; reversed when going back). A browser without it, or a person who asked for less
 * motion, just swaps. `route` is the function from useLocation().
 */
export function go(route: Navigate, path: string, direction: 'forward' | 'back' = 'forward'): void {
  const doc = document as Document & { startViewTransition?: (update: () => Promise<void>) => unknown };
  if (!doc.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    route(path);
    return;
  }
  document.documentElement.dataset['nav'] = direction;
  doc.startViewTransition(async () => {
    route(path);
    await new Promise<void>((done) => setTimeout(done, 60));
  });
}
