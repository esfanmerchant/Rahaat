import type { ComponentChildren } from 'preact';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure, Result } from '../shared/api/problem';
import type { paths } from '../shared/api/schema';
import type { components } from '../shared/api/schema';

/** Types come from the generated OpenAPI client only. */
type S = components['schemas'];
export type CaseSummary = S['CaseSummary'];
export type CaseDetail = S['CaseDetail'];
export type CaseAction = S['CaseActionIn']['action'];
export type DecisionTrace = S['DecisionTrace'];
export type DecisionUserView = S['DecisionUserView'];
export type AuditEntry = S['AuditEntry'];
export type ChainOut = S['ChainOut'];
export type HandoffPackage = S['HandoffPackage'];
export type FieldValue = S['FieldValue_str_'];
export type DocumentCheck = S['DocumentCheck'];
export type AuditQuery = NonNullable<paths['/v1/audit']['get']['parameters']['query']>;

export type Loaded<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'fail'; failure: ApiFailure };

/** Run a call on mount and whenever `deps` change; `reload` runs it again. Stale answers are dropped. */
export function useLoad<T>(run: () => Promise<Result<T>>, deps: readonly unknown[]): [Loaded<T>, () => void] {
  const [loaded, setLoaded] = useState<Loaded<T>>({ state: 'loading' });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);
  useEffect(() => {
    const mine = ++latest.current;
    setLoaded((prev) => (prev.state === 'ok' ? prev : { state: 'loading' }));
    void run().then((res) => {
      if (mine !== latest.current) return;
      setLoaded(res.ok ? { state: 'ok', data: res.data } : { state: 'fail', failure: res.failure });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return [loaded, reload];
}

export const pct = (v: number | null | undefined): string => (v === null || v === undefined ? 'n/a' : `${(v * 100).toFixed(0)}%`);
export const num = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined ? 'n/a' : v.toFixed(digits);

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return 'n/a';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}

export function fmtAge(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 60 * 48) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `${Math.floor(minutes / 1440)}d`;
}

/** Signed countdown to a deadline: "2h 10m left" or "3h overdue". */
export function slaText(due: string | null | undefined, now: number): { text: string; overdue: boolean } {
  if (!due) return { text: 'none', overdue: false };
  const ms = new Date(due).getTime() - now;
  if (Number.isNaN(ms)) return { text: 'n/a', overdue: false };
  const mins = Math.floor(Math.abs(ms) / 60000);
  const text = fmtAge(mins);
  return ms >= 0 ? { text: `${text} left`, overdue: false } : { text: `${text} overdue`, overdue: true };
}

/** A clock that ticks every 30 seconds, for countdowns. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

/** Reason codes read better with spaces. Shown as text only. */
export const humanize = (code: string): string => code.replace(/_/g, ' ');

export function Section({ title, id, children, aside }: { title: string; id: string; children?: ComponentChildren; aside?: ComponentChildren }) {
  return (
    <section aria-labelledby={id} class="border border-line">
      <div class="flex items-center justify-between gap-2 border-b border-line bg-sunken px-3 py-1.5">
        <h2 id={id} class="text-sm font-semibold uppercase tracking-wide text-ink">
          {title}
        </h2>
        {aside}
      </div>
      <div class="p-3">{children}</div>
    </section>
  );
}

type Tone = 'neutral' | 'good' | 'bad' | 'warn' | 'info';
const TONES: Record<Tone, string> = {
  neutral: 'border-line-strong text-ink',
  good: 'border-primary bg-primary-soft text-primary-strong',
  bad: 'border-danger bg-danger-soft text-danger',
  warn: 'border-warning-ink bg-warning-soft text-warning-ink',
  info: 'border-info-strong bg-info-soft text-info-strong',
};

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children?: ComponentChildren }) {
  return <span class={`inline-block rounded-sm border px-1.5 font-mono text-xs ${TONES[tone]}`}>{children}</span>;
}

/** Confidence as a number plus a small bar (the number is the information; the bar is a glance aid). */
export function ConfBar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span class="text-ink-subtle">n/a</span>;
  const w = Math.max(0, Math.min(100, Math.round(value * 100)));
  const tone = value >= 0.9 ? 'bg-primary' : value >= 0.7 ? 'bg-warning-ink' : 'bg-danger';
  return (
    <span class="inline-flex items-center gap-1.5">
      <svg width="48" height="8" viewBox="0 0 100 8" role="img" aria-label={`confidence ${w} percent`} class="shrink-0">
        <rect width="100" height="8" class="fill-surface" />
        <rect width={w} height="8" class={tone === 'bg-primary' ? 'fill-primary' : tone === 'bg-warning-ink' ? 'fill-warning-ink' : 'fill-danger'} />
      </svg>
      <span class="font-mono text-xs tabular-nums">{pct(value)}</span>
    </span>
  );
}

export function Mono({ children, title }: { children?: ComponentChildren; title?: string }) {
  return (
    <span class="break-all font-mono text-xs" title={title}>
      {children}
    </span>
  );
}

export function Th({ children, sort, onSort, active, dir }: { children?: ComponentChildren; sort?: boolean; onSort?: () => void; active?: boolean; dir?: 'asc' | 'desc' }) {
  return (
    <th
      scope="col"
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}
      class="sticky top-0 border-b border-line-strong bg-sunken px-2 py-1 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted"
    >
      {sort ? (
        <button type="button" class="font-semibold uppercase hover:underline" onClick={onSort}>
          {children}
          {active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
        </button>
      ) : (
        children
      )}
    </th>
  );
}

export const TD = 'border-b border-line px-2 py-1 align-top';
export const INPUT = 'h-8 rounded-sm border border-line-strong bg-paper px-2 text-sm text-ink';
