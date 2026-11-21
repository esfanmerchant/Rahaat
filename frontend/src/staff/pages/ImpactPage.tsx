import { useState } from 'preact/hooks';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { HBars, type Tone } from '../charts';
import { Donut, type Seg } from '../dash';
import { Badge, fmtTime, num, pct, Section, TD, Th, useLoad } from '../ui';
import { CountUp } from '../viz';
import { fmtSeconds, getImpact, type Impact } from './wpdApi';

/**
 * Impact: what the system did for this department, counted from its own rows. Every block says what it is measured from;
 * the two numbers that are assumptions are named in the Assumptions box. Replay numbers come from synthetic cases and are labelled so.
 */

const WINDOWS = [30, 90, 365] as const;
const DEFAULT_MINUTES = 10;

function Tile({ id, label, tone, value, format, suffix, hint }: { id: string; label: string; tone: Tone; value: number | null; format?: (n: number) => string; suffix?: string; hint: string }) {
  return (
    <li class={`st-tile st-tone-${tone} flex min-w-0 flex-col gap-1 p-3`} data-testid={`tile-${id}`}>
      <p class="text-xs font-bold uppercase tracking-widest text-ink-muted">{label}</p>
      <p class="st-tile-num rh-num flex items-baseline gap-1 text-4xl font-black leading-none tracking-tight 2xl:text-5xl">
        {value === null ? <span class="text-ink-subtle">n/a</span> : <CountUp value={value} ms={1100} {...(format ? { format } : {})} />}
        {value !== null && suffix ? <span class="text-xl font-bold text-ink-muted">{suffix}</span> : null}
      </p>
      <p class="mt-1 text-xs text-ink-subtle">{hint}</p>
    </li>
  );
}

const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral'> = { settled: 'good', submitted: 'good', approved: 'good', pending_approval: 'warn', failed: 'bad', cancelled: 'bad', reversed: 'bad' };

export function ImpactPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [days, setDays] = useState<number>(90);
  const [minutes, setMinutes] = useState<number>(DEFAULT_MINUTES);
  const [data, reload] = useLoad(() => getImpact(days, minutes), [days, minutes]);

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-4">
      <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-xl font-black tracking-tight">
          Impact
        </h1>
        <span class="text-xs text-ink-subtle">
          {data.state === 'ok' ? `${data.data.department}, last ${data.data.window_days} days, generated ${fmtTime(data.data.generated_at)}. ` : ''}
          Counted from this department&apos;s own decisions, cases and payments.
        </span>
        <div class="ms-auto flex items-center gap-2" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              aria-pressed={days === w}
              class={`h-8 rounded-sm border px-3 text-xs ${days === w ? 'border-primary-strong bg-primary-soft font-semibold text-primary-strong' : 'border-line-strong hover:bg-sunken'}`}
              onClick={() => setDays(w)}
            >
              {w} days
            </button>
          ))}
          <button type="button" class="h-8 rounded-sm border border-line-strong px-3 text-xs hover:bg-sunken" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>

      {data.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Counting decisions, cases and payments…" /> : null}
      {data.state === 'fail' ? <FailureState failure={data.failure} density="staff" onRetry={reload} /> : null}
      {data.state === 'ok' ? <Body d={data.data} minutes={minutes} setMinutes={setMinutes} /> : null}
    </section>
  );
}

function Body({ d, minutes, setMinutes }: { d: Impact; minutes: number; setMinutes: (n: number) => void }) {
  const h = d.handoff;
  const f = d.fraud_stopped;
  const t = d.time_to_decision;
  const fraudTotal = f.forged_cards_flagged + f.duplicates_caught + f.scams_flagged + f.anomaly_cases.total + f.identity_mismatches;
  const empty = h.decisions === 0 && d.payments.count === 0 && f.scams_flagged === 0 && f.anomaly_cases.total === 0;
  const segs: Seg[] = [
    { key: 'auto', label: 'decided automatically', value: h.by_route['auto'] ?? 0, tone: 'ok' },
    { key: 'ask_more', label: 'asked for a proof', value: h.by_route['ask_more'] ?? 0, tone: 'warn' },
    { key: 'human', label: 'sent to a person', value: h.by_route['human'] ?? 0, tone: 'info' },
  ];
  const c = d.cost_per_claim;
  const kinds = Object.entries(t.human_case_by_kind).filter(([, v]) => v.n > 0);

  return (
    <>
      {empty ? (
        <ScreenState kind="empty" density="staff" heading="h2" title="No activity in this window" body="There are no decisions, payments, scam checks or anomaly cases in this window yet. Nothing below is estimated to fill the gap." />
      ) : null}

      <ul class="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6" aria-label="Headline numbers">
        <Tile id="decisions" label="Decisions" tone="info" value={h.decisions} hint={`${d.measured_from['payments'] ?? 0} payments, ${d.measured_from['cases'] ?? 0} cases`} />
        <Tile id="handoff" label="Handoff rate" tone="warn" value={h.handoff_rate === null ? null : Math.round(h.handoff_rate * 100)} suffix="%" hint="share sent to a person" />
        <Tile id="auto-time" label="Automatic, median" tone="ok" value={t.automatic.median_seconds} format={(n) => fmtSeconds(n)} hint={`submission to decision, ${t.automatic.n} timed`} />
        <Tile id="human-time" label="Person, median" tone="info" value={t.human_case.median_seconds} format={(n) => fmtSeconds(n)} hint={`case opened to resolved, ${t.human_case.n} cases`} />
        <Tile id="cost" label="Cost per claim" tone="ok" value={c.per_claim_units === null ? null : Math.round(c.per_claim_units * 100)} format={(n) => (n / 100).toFixed(2)} suffix="units" hint={c.all_to_a_person_per_claim_units === null ? 'expected, from the cost matrix' : `expected; all-to-a-person is ${num(c.all_to_a_person_per_claim_units)}`} />
        <Tile id="fraud" label="Fraud flagged" tone="bad" value={fraudTotal} hint="forged, duplicate, scam, identity, anomaly" />
      </ul>

      <div class="grid gap-4 xl:grid-cols-3">
        <Section id="routes" title="Where decisions go" aside={h.silent_guesses === 0 ? <Badge tone="good">0 silent guesses</Badge> : <Badge tone="bad">{h.silent_guesses} silent guesses</Badge>}>
          {h.decisions === 0 ? (
            <p class="text-ink-muted">No decisions in this window.</p>
          ) : (
            <div class="flex flex-col gap-3">
              <Donut id="impact-routes" segs={segs} centreLabel="decisions" />
              <p class="text-xs text-ink-subtle">
                Handoff {pct(h.handoff_rate)}; not decided automatically {pct(h.not_automatic_rate)}. Routing comes from the cost matrix, never from a fixed threshold.
              </p>
            </div>
          )}
        </Section>

        <Section id="time" title="Time to decision">
          <table class="w-full border-collapse text-sm">
            <thead>
              <tr>
                <Th>Path</Th>
                <Th>n</Th>
                <Th>Median</Th>
                <Th>90th</Th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class={TD}>Automatic (submit to decision)</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{t.automatic.n}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.automatic.median_seconds)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.automatic.p90_seconds)}</td>
              </tr>
              <tr>
                <td class={TD}>Person (case opened to resolved)</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{t.human_case.n}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.human_case.median_seconds)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.human_case.p90_seconds)}</td>
              </tr>
              <tr>
                <td class={TD}>Person, hands on (first look to action)</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{t.human_review_hands_on.n}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.human_review_hands_on.median_seconds)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(t.human_review_hands_on.p90_seconds)}</td>
              </tr>
            </tbody>
          </table>
          {kinds.length > 0 ? (
            <div class="mt-3">
              <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Cases resolved, median minutes by kind</h3>
              <HBars rows={kinds.map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: Math.round((v.median_seconds ?? 0) / 60), cls: 'fill-info-strong' }))} unit=" min" />
            </div>
          ) : null}
          {t.automatic_engine_latency_ms_p50 !== null ? <p class="mt-2 text-xs text-ink-subtle">Engine latency, automatic decisions, median {t.automatic_engine_latency_ms_p50} ms.</p> : null}
        </Section>

        <Section id="fraud" title="Fraud and scams flagged" aside={<Badge>flagged, not proven</Badge>}>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Applications held for a person</h3>
          <HBars
            rows={[
              { label: 'forged cards', value: f.forged_cards_flagged, cls: 'fill-danger' },
              { label: 'duplicates held', value: f.duplicates_caught, cls: 'fill-warning-ink' },
              { label: 'identity mismatch', value: f.identity_mismatches, cls: 'fill-warning-ink' },
              { label: 'anomaly cases', value: f.anomaly_cases.total, cls: 'fill-info-strong' },
            ]}
          />
          <h3 class="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-ink-muted">Messages checked</h3>
          <HBars rows={[{ label: 'scam messages', value: f.scams_flagged, cls: 'fill-danger' }]} />
          <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt class="text-ink-subtle">Scams a person confirmed</dt>
            <dd class="font-mono tabular-nums">{f.scams_confirmed_by_a_person} of {f.scams_flagged}</dd>
            <dt class="text-ink-subtle">Duplicate pairs a person linked</dt>
            <dd class="font-mono tabular-nums">{f.duplicates_linked_by_a_person} of {f.duplicate_candidates}</dd>
            <dt class="text-ink-subtle">Anomaly cases: confirmed / dismissed / open</dt>
            <dd class="font-mono tabular-nums">{f.anomaly_cases.confirmed} / {f.anomaly_cases.dismissed} / {f.anomaly_cases.active}</dd>
            <dt class="text-ink-subtle">Payments stopped</dt>
            <dd class="font-mono tabular-nums">{f.payments_stopped} (Rs {f.payments_stopped_pkr.toLocaleString('en-US')})</dd>
            <dt class="text-ink-subtle">Decisions held by any guard</dt>
            <dd class="font-mono tabular-nums">{f.held_for_a_person_by_a_guard}</dd>
          </dl>
        </Section>
      </div>

      <div class="grid gap-4 xl:grid-cols-3">
        <Section id="cost" title="Cost per claim">
          {c.per_claim_units === null ? (
            <p class="text-ink-muted">No decision with a stored cost in this window.</p>
          ) : (
            <div class="flex flex-col gap-3">
              <HBars
                max={Math.max(c.all_to_a_person_per_claim_units ?? 0, c.per_claim_units, 1)}
                rows={[
                  { label: 'this system, expected', value: Number(c.per_claim_units.toFixed(2)), cls: 'fill-primary' },
                  { label: 'all to a person', value: Number((c.all_to_a_person_per_claim_units ?? 0).toFixed(2)), cls: 'fill-info-strong' },
                ]}
                unit=" u"
              />
              <p class="text-xs text-ink-subtle">
                Units of the department&apos;s cost matrix, from {c.decisions} stored decision traces; about Rs {c.per_claim_pkr_assumed?.toFixed(0)} per claim at the assumed rate below. An expectation, not money spent.
              </p>
            </div>
          )}
        </Section>

        <Section id="payments" title="Payments">
          {d.payments.count === 0 ? (
            <p class="text-ink-muted">No payments in this window.</p>
          ) : (
            <>
              <p class="mb-2 text-sm">
                <span class="rh-num text-2xl font-black">
                  <CountUp value={d.payments.count} />
                </span>{' '}
                payments, Rs <span class="rh-num font-mono">{d.payments.amount_pkr.toLocaleString('en-US')}</span> in total; settled Rs <span class="rh-num font-mono">{d.payments.settled_pkr.toLocaleString('en-US')}</span>.
              </p>
              <table class="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <Th>Status</Th>
                    <Th>Count</Th>
                    <Th>Amount (Rs)</Th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(d.payments.by_status).map(([s, v]) => (
                    <tr key={s}>
                      <td class={TD}>
                        <Badge tone={STATUS_TONE[s] ?? 'neutral'}>{s.replace(/_/g, ' ')}</Badge>
                      </td>
                      <td class={`${TD} text-end font-mono tabular-nums`}>{v.count}</td>
                      <td class={`${TD} text-end font-mono tabular-nums`}>{v.amount_pkr.toLocaleString('en-US')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Section>

        <Section id="saved" title="Time saved" aside={<Badge tone="warn">estimate</Badge>}>
          <p class="text-sm">
            <span class="rh-num text-3xl font-black">
              <CountUp value={Math.round(d.time_saved.hands_on_hours_saved * 10)} format={(n) => (n / 10).toFixed(1)} />
            </span>{' '}
            officer hours spared across {d.time_saved.automatic_decisions} automatic decisions, at {d.time_saved.minutes_per_manual_review_used} min each.
          </p>
          <dl class="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt class="text-ink-subtle">Minutes per review comes from</dt>
            <dd>{d.time_saved.hands_on_source === 'assumed_minutes_per_manual_review' ? 'an assumption (no review timed yet)' : 'measured officer review times'}</dd>
            <dt class="text-ink-subtle">Waiting time avoided</dt>
            <dd class="font-mono tabular-nums">{d.time_saved.waiting_hours_avoided === null ? 'n/a' : `${d.time_saved.waiting_hours_avoided} h`}</dd>
          </dl>
          <p class="mt-2 text-xs text-ink-subtle">{d.time_saved.label}</p>
        </Section>
      </div>

      <div class="grid gap-4 xl:grid-cols-3">
        <Section id="replay" title="Replay evaluation" aside={<Badge tone="warn">synthetic</Badge>}>
          {d.replay.cases === null ? (
            <p class="text-ink-muted">{d.replay.label}</p>
          ) : (
            <div class="flex flex-col gap-2">
              <dl class="grid grid-cols-2 gap-2">
                <Stat label="Labelled cases" value={String(d.replay.cases)} />
                <Stat label="Accuracy when automatic" value={pct(d.replay.accuracy_of_automatic)} />
                <Stat label="False approvals" value={String(d.replay.false_approvals)} />
                <Stat label="False rejections" value={String(d.replay.false_rejections)} />
                <Stat label="Unnecessary handoffs" value={String(d.replay.unnecessary_handoffs)} />
                <Stat label="ECE" value={num(d.replay.ece, 3)} />
              </dl>
              <p class="text-xs text-ink-subtle">{d.replay.label}</p>
            </div>
          )}
        </Section>

        <section aria-labelledby="assumptions" class="st-panel border-2 border-warning-ink xl:col-span-2" data-testid="assumptions">
          <div class="st-panel-head flex items-center justify-between gap-2 px-3 py-1.5">
            <h2 id="assumptions" class="text-xs font-bold uppercase tracking-widest text-ink-muted">
              Assumptions
            </h2>
            <Badge tone="warn">not measured</Badge>
          </div>
          <div class="flex flex-col gap-3 p-3">
            <p class="text-sm">Everything on this page is counted or measured except the numbers below. Change one and the page recomputes.</p>
            <ul class="flex flex-col gap-2">
              {d.assumptions.map((a) => (
                <li key={a.name} class="grid gap-1 border border-line px-2 py-1.5 md:grid-cols-[17rem_13rem_1fr] md:items-center md:gap-3">
                  <code class="font-mono text-xs">{a.name}</code>
                  {a.name === 'assumed_minutes_per_manual_review' ? (
                    <label class="flex items-center gap-1 text-xs">
                      <span class="sr-only">{a.name}</span>
                      <input
                        type="number"
                        min={1}
                        max={240}
                        step={1}
                        value={minutes}
                        class="h-8 w-20 rounded-md border border-line-strong bg-paper px-2 font-mono text-sm text-ink"
                        onChange={(e) => {
                          const n = Number(e.currentTarget.value);
                          if (Number.isFinite(n) && n >= 1 && n <= 240) setMinutes(n);
                        }}
                      />
                      {a.unit}
                    </label>
                  ) : (
                    <span class="font-mono text-sm">
                      {a.value} {a.unit}
                    </span>
                  )}
                  <span class="text-xs text-ink-muted">{a.used_for}</span>
                </li>
              ))}
            </ul>
            <ul class="list-disc ps-5 text-xs text-ink-subtle">
              {d.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <p class="text-xs text-ink-subtle">
              Rows behind the numbers: {Object.entries(d.measured_from).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div class="border border-line px-2 py-1">
      <dt class="text-xs text-ink-subtle">{label}</dt>
      <dd class="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
