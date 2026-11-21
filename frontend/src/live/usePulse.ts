import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../shared/api/client';
import { call, type ApiFailure } from '../shared/api/problem';
import type { Pulse } from './types';

export const REFRESH_MS = 15000;

export type PulseState =
  | { kind: 'loading' }
  | { kind: 'ready'; pulse: Pulse; stale: boolean }
  | { kind: 'error'; failure: ApiFailure };

/** Loads the pulse and refreshes it every 15 s while the tab is visible. Keeps the last good answer when a refresh fails. */
export function usePulse(): { state: PulseState; reload: () => void } {
  const [state, setState] = useState<PulseState>({ kind: 'loading' });
  const last = useRef<Pulse | null>(null);

  const load = useCallback(async () => {
    const result = await call(api.GET('/v1/public/pulse'));
    if (result.ok) {
      last.current = result.data;
      setState({ kind: 'ready', pulse: result.data, stale: false });
    } else if (last.current) {
      setState({ kind: 'ready', pulse: last.current, stale: true });
    } else {
      setState({ kind: 'error', failure: result.failure });
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      if (!document.hidden) void load();
    }, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  return { state, reload: () => void load() };
}
