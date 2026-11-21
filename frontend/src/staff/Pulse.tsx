import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import { CountUp } from './viz';

/**
 * The live pulse: five counters from endpoints that already exist, refreshed every 15 seconds.
 * A counter whose endpoint answers 403 for this role (or fails) is left out, never faked.
 * "Today" is the UTC day, the same clock the rest of the console shows. Counts come from one page of up to 100
 * rows; when more exist the number carries a plus sign.
 */
interface Stat {
  key: string;
  label: string;
  value: number;
  plus: boolean;
  hint: string;
  tone: 'plain' | 'ok' | 'info' | 'bad';
  format?: (n: number) => string;
}

const todayUtc = (): string => new Date().toISOString().slice(0, 10);
const isToday = (iso: string | null | undefined): boolean => Boolean(iso) && (iso as string).slice(0, 10) === todayUtc();
const rupees = (n: number): string => `Rs ${n.toLocaleString('en-US')}`;

async function load(): Promise<Stat[]> {
  const day = todayUtc();
  const [cases, decisions, payments, scams] = await Promise.all([
    call(api.GET('/v1/cases', { params: { query: { status: 'active', limit: 100 } } })),
    call(api.GET('/v1/decisions', { params: { query: { decided_from: day, limit: 100 } } })),
    call(api.GET('/v1/payments', { params: { query: { limit: 100 } } })),
    call(api.GET('/v1/scam/reports', { params: { query: { limit: 100 } } })),
  ]);
  const out: Stat[] = [];
  if (cases.ok) {
    out.push({ key: 'open', label: 'Open cases', value: cases.data.items.length, plus: Boolean(cases.data.next_cursor), hint: 'Active cases in the review queue', tone: 'info' });
  }
  if (decisions.ok) {
    const items = decisions.data.items;
    const more = Boolean(decisions.data.next_cursor);
    out.push({ key: 'decided', label: 'Decided today', value: items.length, plus: more, hint: 'Decisions recorded since 00:00 UTC', tone: 'plain' });
  }
  if (payments.ok) {
    const today = payments.data.items.filter((p) => isToday(p.created_at) && p.status === 'settled');
    const sum = today.reduce((a, p) => a + p.amount_pkr, 0);
    out.push({
      key: 'paid',
      label: 'Paid today',
      value: sum,
      plus: Boolean(payments.data.next_cursor),
      hint: `${today.length} settled payment${today.length === 1 ? '' : 's'} since 00:00 UTC (mock rail)`,
      tone: 'ok',
      format: rupees,
    });
  }
  if (decisions.ok) {
    const human = decisions.data.items.filter((d) => d.route === 'human').length;
    out.push({ key: 'human', label: 'Sent to a person', value: human, plus: Boolean(decisions.data.next_cursor), hint: 'Decisions today that the system handed to an officer', tone: 'info' });
  }
  if (scams.ok) {
    const flagged = scams.data.items.filter((r) => isToday(r.created_at) && r.certainty === 'likely_scam').length;
    out.push({
      key: 'scams',
      label: 'Scams flagged',
      value: flagged,
      plus: Boolean(scams.data.next_cursor) && scams.data.items.every((r) => isToday(r.created_at)),
      hint: 'Messages today that the checker called a likely scam',
      tone: 'bad',
    });
  }
  return out;
}

const REFRESH_MS = 15000;

export function PulseStrip() {
  const [stats, setStats] = useState<Stat[] | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const run = async (): Promise<void> => {
      if (document.hidden) return;
      try {
        const next = await load();
        if (!alive.current) return;
        setStats(next);
        setAt(new Date());
        setFailed(false);
      } catch {
        if (alive.current) setFailed(true);
      }
    };
    void run();
    const id = window.setInterval(() => void run(), REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden) void run();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive.current = false;
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  const tone = (t: Stat['tone']): string => (t === 'ok' ? 'text-emerald-glow' : t === 'bad' ? 'text-madder-glow' : t === 'info' ? 'text-indigo-glow' : 'text-night-ink');

  return (
    <section aria-label="Live counters" class="st-pulse flex flex-wrap items-center gap-y-1 px-3 py-1.5">
      <div class="flex items-center gap-2 pe-3 text-xs text-night-muted">
        <span class="st-live" aria-hidden="true" />
        <span class="font-semibold uppercase tracking-wide">Live</span>
      </div>
      {stats === null ? (
        <span class="text-xs text-night-muted" role="status">
          {failed ? 'Counters unavailable.' : 'Reading the counters…'}
        </span>
      ) : stats.length === 0 ? (
        <span class="text-xs text-night-muted">No counters are available for this role.</span>
      ) : (
        stats.map((s) => (
          <div key={s.key} class="st-stat flex items-baseline gap-2" title={s.hint}>
            <span class={`rh-num text-xl font-black leading-none tracking-tight ${tone(s.tone)}`}>
              <CountUp value={s.value} {...(s.format ? { format: s.format } : {})} />
              {s.plus ? '+' : ''}
            </span>
            <span class="text-xs text-night-muted">{s.label}</span>
          </div>
        ))
      )}
      <span class="ms-auto ps-3 text-xs text-night-muted" aria-live="off">
        {failed ? 'Refresh failed, showing the last numbers. ' : ''}
        {at ? `Updated ${at.toISOString().slice(11, 19)}Z, every 15 s` : ''}
      </span>
    </section>
  );
}
