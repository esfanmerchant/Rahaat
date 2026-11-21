import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../shared/api/client';
import { call, type ApiFailure } from '../shared/api/problem';
import type { Pulse } from './types';

export const REFRESH_MS = 15000;

/** 15 s by default; `?refresh=5` (3 to 60) speeds it up for the demo. */
function refreshMs(): number {
  const n = Number(new URLSearchParams(window.location.search).get('refresh'));
  return Number.isFinite(n) && n >= 3 && n <= 60 ? Math.round(n * 1000) : REFRESH_MS;
}

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
    }, refreshMs());
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  // Test hook, only under ?perf: raises a few live counters by one so the counter flash can be checked without a real approval.
  useEffect(() => {
    if (!window.location.search.includes('perf')) return;
    const w = window as unknown as { __loomBump?: () => void };
    w.__loomBump = () =>
      setState((s) => {
        if (s.kind !== 'ready') return s;
        const l = s.pulse.live;
        const route = { ...l.decisions_by_route, auto: (l.decisions_by_route.auto ?? 0) + 1 };
        const payments = { ...l.payments, sent: l.payments.sent + 1, settled: l.payments.settled + 1, settled_amount_pkr: l.payments.settled_amount_pkr + 15000 };
        return { ...s, pulse: { ...s.pulse, live: { ...l, decisions_by_route: route, payments } } };
      });
    return () => {
      delete w.__loomBump;
    };
  }, []);

  return { state, reload: () => void load() };
}
