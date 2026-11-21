import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN } from '../kit';
import { Empty, LoadView } from '../loadview';
import { Badge, fmtTime, humanize, Section, useLoad } from '../ui';

type Usage = components['schemas']['UsageOut'];
type Metric = components['schemas']['MetricUsage'];

/** What the service does once a metric is used up (modules/plans), so nobody is surprised. */
const WHAT_HAPPENS: Record<string, string> = {
  ocr: 'photos are kept and wait for a person',
  sms: 'messages stay in the app',
  ai_calls: 'voice stops, typing still works',
  applications: 'new applications are refused with 429',
  api_calls: 'partner keys are refused with 429',
};

const nf = (n: number): string => n.toLocaleString('en-US');

/** Warms as the limit nears: calm below 60 percent, saffron to 85, madder after. The words always say the percent too. */
function level(m: Metric): 'l0' | 'l2' | 'l3' | 'unl' {
  if (m.limit === null) return 'unl';
  const p = m.percent_used ?? (m.limit > 0 ? (m.used / m.limit) * 100 : 0);
  if (m.reached || p >= 85) return 'l3';
  if (p >= 60) return 'l2';
  return 'l0';
}

const percentOf = (m: Metric): number => Math.max(0, Math.min(100, m.percent_used ?? (m.limit ? (m.used / m.limit) * 100 : 0)));

/** What the department has used this month against its plan, and the five months before. */
export function UsagePage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/admin/usage')), []);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Usage and plan
        </h1>
        <button type="button" class={BTN} onClick={reload}>
          Refresh
        </button>
      </div>
      <LoadView state={loaded} reload={reload} what="usage and plan" rows={5}>
        {(u) => <UsageBody usage={u} />}
      </LoadView>
    </section>
  );
}

function UsageBody({ usage }: { usage: Usage }) {
  const metrics = usage.metrics;
  const hottest = [...metrics].sort((a, b) => percentOf(b) - percentOf(a))[0];
  const [pick, setPick] = useState<string>(hottest?.metric ?? metrics[0]?.metric ?? '');
  const reached = metrics.filter((m) => m.reached);
  return (
    <div class="flex flex-col gap-4">
      <div class="st-panel flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <div>
          <p class="text-xs uppercase tracking-widest text-ink-muted">Plan</p>
          <p class="text-2xl font-black tracking-tight" data-testid="plan-name">
            {usage.plan ? usage.plan.name : 'No plan assigned'}
          </p>
          {usage.plan ? <p class="font-mono text-xs text-ink-subtle">{usage.plan.code}</p> : <p class="text-xs text-ink-subtle">Without a plan every metric is unlimited, and still counted.</p>}
        </div>
        <div>
          <p class="text-xs uppercase tracking-widest text-ink-muted">This month</p>
          <p class="font-mono text-lg">{usage.period}</p>
        </div>
        <div>
          <p class="text-xs uppercase tracking-widest text-ink-muted">Counters reset</p>
          <p class="font-mono text-lg" data-testid="resets-at">
            {fmtTime(usage.resets_at)}
          </p>
        </div>
        {reached.length > 0 ? (
          <p role="alert" class="st-chip bad" style={{ height: 'auto', whiteSpace: 'normal', padding: '0.25rem 0.6rem' }}>
            Limit reached: {reached.map((m) => `${m.label} (${WHAT_HAPPENS[m.metric] ?? 'further use is refused until the reset'})`).join('; ')}.
          </p>
        ) : null}
      </div>

      <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Section id="metrics" title="Metered this month">
          {metrics.length === 0 ? (
            <Empty title="Nothing is metered" body="No metric has been counted for this department yet." />
          ) : (
            <ul class="flex flex-col gap-4">
              {metrics.map((m, i) => (
                <MetricRow key={m.metric} m={m} i={i} selected={pick === m.metric} onPick={() => setPick(m.metric)} />
              ))}
            </ul>
          )}
        </Section>
        <Section id="history" title="Last six months">
          {metrics.length === 0 ? <Empty title="No history" body="Counts appear here after the first metered action." /> : <History usage={usage} metric={pick} onPick={setPick} />}
        </Section>
      </div>
    </div>
  );
}

function MetricRow({ m, i, selected, onPick }: { m: Metric; i: number; selected: boolean; onPick: () => void }) {
  const lv = level(m);
  const pct = percentOf(m);
  return (
    <li class="st-row-in flex flex-col gap-1" style={{ '--i': i }} data-testid={`metric-${m.metric}`}>
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <button type="button" class="font-semibold underline-offset-2 hover:underline" aria-pressed={selected} onClick={onPick} title="Show this metric in the history chart">
          {m.label}
        </button>
        <span class="rh-num font-mono text-sm">
          {nf(m.used)} <span class="text-ink-subtle">of</span> {m.limit === null ? 'unlimited' : nf(m.limit)}
          {m.limit === null ? null : <span class="ms-2 text-ink-muted">{Math.round(pct)}%</span>}
        </span>
      </div>
      <div class={`st-meter ${lv}`} role="progressbar" aria-label={`${m.label} used`} aria-valuemin={0} aria-valuemax={m.limit ?? undefined} aria-valuenow={m.used} aria-valuetext={m.limit === null ? `${nf(m.used)}, no limit` : `${nf(m.used)} of ${nf(m.limit)}, ${Math.round(pct)} percent`}>
        <i style={{ width: m.limit === null ? '100%' : `${Math.max(pct, m.used > 0 ? 1.5 : 0)}%` }} />
      </div>
      <div class="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        {m.reached ? <Badge tone="bad">limit reached</Badge> : lv === 'l3' ? <Badge tone="bad">nearly full</Badge> : lv === 'l2' ? <Badge tone="warn">filling up</Badge> : lv === 'unl' ? <Badge tone="info">no limit on this plan</Badge> : <Badge tone="good">within the limit</Badge>}
        <span class="font-mono">{humanize(m.metric)}</span>
        {m.limit !== null ? <span>{nf(Math.max(0, m.limit - m.used))} left</span> : null}
      </div>
    </li>
  );
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (period: string): string => {
  const m = /^(\d{4})-(\d{2})/.exec(period);
  return m ? `${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]!.slice(2)}` : period;
};

/** Six bars, one per month, for one metric; the plan limit is a dashed line. Hand-drawn SVG, a table is the text alternative. */
function History({ usage, metric, onPick }: { usage: Usage; metric: string; onPick: (m: string) => void }) {
  const current = usage.metrics.find((m) => m.metric === metric) ?? usage.metrics[0];
  if (!current) return null;
  const rows = [
    ...usage.history.map((h) => ({ period: h.period, value: Number((h.counts as Record<string, unknown>)[current.metric] ?? 0) })),
    { period: usage.period, value: current.used },
  ]
    .sort((a, b) => a.period.localeCompare(b.period))
    .slice(-6);
  const limit = current.limit;
  const top = Math.max(1, limit ?? 0, ...rows.map((r) => r.value)) * 1.12;
  const W = 460;
  const H = 230;
  const m = { l: 44, r: 12, t: 22, b: 30 };
  const bw = (W - m.l - m.r) / rows.length;
  const y = (v: number) => H - m.b - (v / top) * (H - m.t - m.b);
  const tone = (v: number): string => (limit === null ? 'fill-info-strong' : v / limit >= 0.85 ? 'fill-danger' : v / limit >= 0.6 ? 'fill-warning-ink' : 'fill-primary');
  const toneKey = (v: number): string => (limit === null ? 'info' : v / limit >= 0.85 ? 'bad' : v / limit >= 0.6 ? 'warn' : 'ok');
  const ticks = [0, 0.5, 1].map((f) => Math.round(top * f));
  return (
    <div class="flex flex-col gap-2">
      <div class="flex flex-wrap gap-1" role="group" aria-label="Metric shown in the chart">
        {usage.metrics.map((x) => (
          <button key={x.metric} type="button" class={`st-chip ${x.metric === current.metric ? 'info' : ''} hover:brightness-125`} aria-pressed={x.metric === current.metric} onClick={() => onPick(x.metric)}>
            {x.label}
          </button>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} class="st-chart w-full" role="img" aria-label={`${current.label} per month: ${rows.map((r) => `${monthLabel(r.period)} ${nf(r.value)}`).join(', ')}${limit === null ? '. No limit.' : `. Limit ${nf(limit)} a month.`}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke="var(--st-grid)" stroke-width="1" />
            <text x={m.l - 6} y={y(t) + 4} text-anchor="end" class="fill-ink-muted" font-size="11">
              {nf(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x = m.l + i * bw + bw * 0.18;
          const w = bw * 0.64;
          const h = Math.max(0, H - m.b - y(r.value));
          const last = i === rows.length - 1;
          return (
            <g key={r.period} class={`st-tone-${toneKey(r.value)}`}>
              <rect x={x} y={y(r.value)} width={w} height={h} rx="3" class={`${tone(r.value)} st-bar-fill st-glow`} />
              <text x={x + w / 2} y={y(r.value) - 5} text-anchor="middle" class="fill-ink" font-size="11" font-weight={last ? 700 : 400}>
                {nf(r.value)}
              </text>
              <text x={x + w / 2} y={H - 10} text-anchor="middle" class={last ? 'fill-ink' : 'fill-ink-muted'} font-size="11" font-weight={last ? 700 : 400}>
                {monthLabel(r.period)}
              </text>
            </g>
          );
        })}
        {limit !== null ? (
          <g>
            <line x1={m.l} x2={W - m.r} y1={y(limit)} y2={y(limit)} class="stroke-danger" stroke-width="1.5" stroke-dasharray="5 4" />
            <text x={m.l + 4} y={y(limit) - 4} text-anchor="start" class="fill-danger" font-size="11">
              limit {nf(limit)}
            </text>
          </g>
        ) : null}
      </svg>
      <table class="sr-only">
        <caption>{current.label} per month</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Used</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.period}>
              <td>{r.period}</td>
              <td>{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p class="text-xs text-ink-subtle">
        {limit === null ? 'This plan has no limit on this metric.' : 'The dashed line is the monthly limit of the plan.'} The last bar is the month so far.
      </p>
    </div>
  );
}
