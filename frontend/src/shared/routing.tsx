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
