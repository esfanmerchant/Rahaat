import { useState } from 'preact/hooks';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { HBars, type Tone } from '../charts';
import { Donut, type Seg } from '../dash';
import { Badge, fmtTime, num, pct, TD, Th, useLoad } from '../ui';
import { CountUp } from '../viz';
import { SectionTabs } from '../SectionTabs';
import { Card, Info } from './pg';
import { fmtSeconds, getImpact, type Impact } from './wpdApi';

/**
 * Impact: what the system did for this department, counted from its own rows. Every block says what it is measured from;
 * the two numbers that are assumptions are named in the Assumptions box. Replay numbers come from synthetic cases and are labelled so.
 */

const WINDOWS = [30, 90, 365] as const;
const DEFAULT_MINUTES = 10;

function Tile({ id, label, tone, value, format, suffix, hint, i }: { id: string; label: string; tone: Tone; value: number | null; format?: (n: number) => string; suffix?: string; hint: string; i: number }) {
  return (
    <li class={`pg-tile pg-rise st-tone-${tone}`} style={{ '--i': i }} data-testid={`tile-${id}`}>
      <p class="pg-cap">
        {label}
        <Info label={`About ${label}`}>{hint}</Info>
      </p>
      <p class="pg-num rh-num">
        {value === null ? <span class="text-ink-subtle">n/a</span> : <CountUp value={value} ms={1100} {...(format ? { format } : {})} />}
        {value !== null && suffix ? <small>{suffix}</small> : null}
      </p>
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
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="pg-head pg-rise">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} style={{ fontSize: '1.5rem' }}>
          Impact
        </h1>
        {data.state === 'ok' ? (
          <>
            <span class="st-chip" title="Department">{data.data.department}</span>
            <span class="st-chip" title={`Generated ${fmtTime(data.data.generated_at)}`}>{data.data.window_days} days</span>
          </>
        ) : null}
        <Info label="About this page">Counted from this department&apos;s own decisions, cases and payments. Only the numbers in Assumptions are not measured.</Info>
        <div class="ms-auto flex items-center gap-2">
          <div class="pg-seg" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button key={w} type="button" aria-pressed={days === w} onClick={() => setDays(w)}>
                {w} days
              </button>
            ))}
          </div>
          <button type="button" class="h-8 rounded-full border border-line-strong px-3 text-xs hover:bg-sunken" onClick={reload}>
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
        <ScreenState kind="empty" density="staff" heading="h2" title="No activity in this window" body="No decisions, payments, scam checks or anomaly cases yet. Nothing is estimated to fill the gap." />
      ) : null}

      <SectionTabs
        label="Impact sections"
        sections={[
          { id: 'summary', label: 'Summary' },
          { id: 'routes', label: 'Routes & time' },
          { id: 'fraud', label: 'Fraud', badge: fraudTotal || undefined },
          { id: 'assumptions', label: 'Assumptions', badge: '!' },
        ]}
      >
        {(tab) => {
          if (tab === 'summary') {
            return (
              <div class="flex flex-col gap-3">
                <ul class="pg-tiles" aria-label="Headline numbers">
                  <Tile i={0} id="decisions" label="Decisions" tone="info" value={h.decisions} hint={`${d.measured_from['payments'] ?? 0} payments, ${d.measured_from['cases'] ?? 0} cases behind it`} />
                  <Tile i={1} id="handoff" label="Handoff" tone="warn" value={h.handoff_rate === null ? null : Math.round(h.handoff_rate * 100)} suffix="%" hint="Share of decisions sent to a person." />
                  <Tile i={2} id="auto-time" label="Auto median" tone="ok" value={t.automatic.median_seconds === null ? null : Math.round(t.automatic.median_seconds * 10)} format={(n) => fmtSeconds(n / 10)} hint={`Submission to decision, ${t.automatic.n} timed.`} />
                  <Tile i={3} id="human-time" label="Person median" tone="info" value={t.human_case.median_seconds === null ? null : Math.round(t.human_case.median_seconds * 10)} format={(n) => fmtSeconds(n / 10)} hint={`Case opened to resolved, ${t.human_case.n} cases.`} />
                  <Tile i={4} id="cost" label="Cost / claim" tone="ok" value={c.per_claim_units === null ? null : Math.round(c.per_claim_units * 100)} format={(n) => (n / 100).toFixed(2)} suffix="units" hint={c.all_to_a_person_per_claim_units === null ? 'Expected, from the cost matrix.' : `Expected, from the cost matrix. All to a person: ${num(c.all_to_a_person_per_claim_units)}.`} />
                  <Tile i={5} id="fraud" label="Fraud flagged" tone="bad" value={fraudTotal} hint="Forged, duplicate, scam, identity and anomaly flags. Flagged, not proven." />
                </ul>
                <div class="pg-grid pg-3">
                  <Card title="Cost" i={6} aside={<Info label="About cost">Units of the department&apos;s cost matrix, from {c.decisions} stored decision traces. An expectation, not money spent.</Info>}>
                    {c.per_claim_units === null ? (
                      <p class="text-ink-muted">No stored cost.</p>
                    ) : (
                      <div class="flex flex-col gap-2">
                        <HBars
                          max={Math.max(c.all_to_a_person_per_claim_units ?? 0, c.per_claim_units, 1)}
                          rows={[
                            { label: 'this system', value: Number(c.per_claim_units.toFixed(2)), cls: 'fill-primary' },
                            { label: 'all to a person', value: Number((c.all_to_a_person_per_claim_units ?? 0).toFixed(2)), cls: 'fill-info-strong' },
                          ]}
                          unit=" u"
                        />
                        <span class="st-chip warn" title="At the assumed rate in Assumptions">
                          about Rs {c.per_claim_pkr_assumed?.toFixed(0)} per claim
                        </span>
                      </div>
                    )}
                  </Card>
                  <Card title="Payments" i={7}>
                    {d.payments.count === 0 ? (
                      <p class="text-ink-muted">No payments.</p>
                    ) : (
                      <div class="flex flex-col gap-2">
                        <p class="flex items-baseline gap-2">
                          <span class="pg-big rh-num">
                            <CountUp value={d.payments.count} />
                          </span>
                          <span class="text-ink-muted">Rs {d.payments.amount_pkr.toLocaleString('en-US')}</span>
                        </p>
                        <div class="pg-chips">
                          {Object.entries(d.payments.by_status).map(([k, v]) => (
                            <Badge key={k} tone={STATUS_TONE[k] ?? 'neutral'}>
                              {k.replace(/_/g, ' ')} {v.count}
                            </Badge>
                          ))}
                        </div>
                        <span class="st-chip ok self-start" title="Settled amount">settled Rs {d.payments.settled_pkr.toLocaleString('en-US')}</span>
                      </div>
                    )}
                  </Card>
                  <Card title="Time saved" i={8} aside={<><Badge tone="warn">estimate</Badge><Info label="About time saved">{d.time_saved.label}</Info></>}>
                    <p class="flex items-baseline gap-2">
                      <span class="pg-big rh-num">
                        <CountUp value={Math.round(d.time_saved.hands_on_hours_saved * 10)} format={(n) => (n / 10).toFixed(1)} />
                      </span>
                      <span class="text-ink-muted">officer hours</span>
                    </p>
                    <div class="pg-chips mt-2">
                      <span class="st-chip">{d.time_saved.automatic_decisions} automatic</span>
                      <span class="st-chip warn">{d.time_saved.minutes_per_manual_review_used} min each</span>
                      <span class="st-chip" title="Waiting time avoided">{d.time_saved.waiting_hours_avoided === null ? 'wait n/a' : `${d.time_saved.waiting_hours_avoided} h wait avoided`}</span>
                    </div>
                  </Card>
                </div>
              </div>
            );
          }
          if (tab === 'routes') {
            return (
              <div class="pg-grid pg-2">
                <Card title="Routes" i={0} aside={h.silent_guesses === 0 ? <Badge tone="good">0 silent guesses</Badge> : <Badge tone="bad">{h.silent_guesses} silent guesses</Badge>}>
                  {h.decisions === 0 ? (
                    <p class="text-ink-muted">No decisions.</p>
                  ) : (
                    <div class="flex flex-col gap-2">
                      <Donut id="impact-routes" segs={segs} centreLabel="decisions" />
                      <div class="pg-chips">
                        <span class="st-chip warn">handoff {pct(h.handoff_rate)}</span>
                        <span class="st-chip info">not automatic {pct(h.not_automatic_rate)}</span>
                        <Info label="About routing">Routing comes from the cost matrix, never from a fixed threshold.</Info>
                      </div>
                    </div>
                  )}
                </Card>
                <Card title="Time" i={1} aside={t.automatic_engine_latency_ms_p50 !== null ? <span class="st-chip font-mono" title="Engine latency, automatic decisions, median">{t.automatic_engine_latency_ms_p50} ms</span> : undefined}>
                  <table class="w-full border-collapse text-sm">
                    <thead>
                      <tr>
                        <Th>Path</Th>
                        <Th><span class="block text-end">n</span></Th>
                        <Th><span class="block text-end">Median</span></Th>
                        <Th><span class="block text-end">90th</span></Th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ['Automatic', t.automatic, 'Submit to decision'],
                        ['Person', t.human_case, 'Case opened to resolved'],
                        ['Hands on', t.human_review_hands_on, 'First look to action'],
                      ].map(([name, row, tip]) => {
                        const r = row as typeof t.automatic;
                        return (
                          <tr key={name as string}>
                            <td class={TD} title={tip as string}>{name as string}</td>
                            <td class={`${TD} text-end font-mono tabular-nums`}>{r.n}</td>
                            <td class={`${TD} text-end font-mono font-bold tabular-nums`}>{fmtSeconds(r.median_seconds)}</td>
                            <td class={`${TD} text-end font-mono tabular-nums`}>{fmtSeconds(r.p90_seconds)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {kinds.length > 0 ? (
                    <div class="mt-3">
                      <p class="pg-cap mb-1">Median minutes by kind</p>
                      <HBars rows={kinds.map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: Math.round((v.median_seconds ?? 0) / 60), cls: 'fill-info-strong' }))} unit=" min" />
                    </div>
                  ) : null}
                </Card>
                <Card title="Replay" i={2} class="pg-2-span" aside={<><Badge tone="warn">synthetic</Badge><Info label="About replay">{d.replay.label}</Info></>}>
                  {d.replay.cases === null ? (
                    <p class="text-ink-muted">No replay run.</p>
                  ) : (
                    <dl class="grid grid-cols-3 gap-2 md:grid-cols-6">
                      <Stat label="Cases" value={String(d.replay.cases)} />
                      <Stat label="Accuracy" value={pct(d.replay.accuracy_of_automatic)} />
                      <Stat label="False approvals" value={String(d.replay.false_approvals)} />
                      <Stat label="False rejections" value={String(d.replay.false_rejections)} />
                      <Stat label="Needless handoffs" value={String(d.replay.unnecessary_handoffs)} />
                      <Stat label="ECE" value={num(d.replay.ece, 3)} />
                    </dl>
                  )}
                </Card>
              </div>
            );
          }
          if (tab === 'fraud') {
            return (
              <div class="pg-grid pg-2">
                <Card title="Held for a person" i={0} aside={<Badge>flagged, not proven</Badge>}>
                  <HBars
                    rows={[
                      { label: 'forged cards', value: f.forged_cards_flagged, cls: 'fill-danger' },
                      { label: 'duplicates held', value: f.duplicates_caught, cls: 'fill-warning-ink' },
                      { label: 'identity mismatch', value: f.identity_mismatches, cls: 'fill-warning-ink' },
                      { label: 'anomaly cases', value: f.anomaly_cases.total, cls: 'fill-info-strong' },
                      { label: 'scam messages', value: f.scams_flagged, cls: 'fill-danger' },
                    ]}
                  />
                </Card>
                <Card title="Outcomes" i={1}>
                  <div class="grid grid-cols-2 gap-3">
                    <div class="pg-tile st-tone-ok">
                      <p class="pg-cap">Scams confirmed</p>
                      <p class="pg-num rh-num">{f.scams_confirmed_by_a_person}<small>of {f.scams_flagged}</small></p>
                    </div>
                    <div class="pg-tile st-tone-info">
                      <p class="pg-cap">Duplicates linked</p>
                      <p class="pg-num rh-num">{f.duplicates_linked_by_a_person}<small>of {f.duplicate_candidates}</small></p>
                    </div>
                    <div class="pg-tile st-tone-bad">
                      <p class="pg-cap">Payments stopped</p>
                      <p class="pg-num rh-num">{f.payments_stopped}<small>Rs {f.payments_stopped_pkr.toLocaleString('en-US')}</small></p>
                    </div>
                    <div class="pg-tile st-tone-warn">
                      <p class="pg-cap">Held by a guard</p>
                      <p class="pg-num rh-num">{f.held_for_a_person_by_a_guard}</p>
                    </div>
                  </div>
                  <div class="pg-chips mt-3" title="Anomaly cases">
                    <span class="st-chip ok">{f.anomaly_cases.confirmed} confirmed</span>
                    <span class="st-chip unk">{f.anomaly_cases.dismissed} dismissed</span>
                    <span class="st-chip info">{f.anomaly_cases.active} open</span>
                  </div>
                </Card>
              </div>
            );
          }
          return (
            <section aria-labelledby="assumptions" class="pg-warnbox pg-rise" data-testid="assumptions">
              <div class="pg-card-head">
                <h2 id="assumptions">Assumptions</h2>
                <span class="pg-aside">
                  <Badge tone="warn">not measured</Badge>
                  <Info label="About assumptions">
                    Everything on this page is counted or measured except the numbers here. Change one and the page recomputes.
                    <ul class="mt-2 list-disc ps-4">
                      {d.notes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </Info>
                </span>
              </div>
              <ul class="flex flex-col gap-2">
                {d.assumptions.map((a) => (
                  <li key={a.name} class="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2">
                    <code class="min-w-0 flex-1 font-mono text-xs" style={{ flexBasis: '15rem' }}>{a.name}</code>
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
                      <span class="font-mono text-sm font-bold">
                        {a.value} {a.unit}
                      </span>
                    )}
                    <Info label={`Used for ${a.name}`}>{a.used_for}</Info>
                  </li>
                ))}
              </ul>
              <p class="pg-chips mt-3" title="Rows behind the numbers">
                {Object.entries(d.measured_from).map(([k, v]) => (
                  <span key={k} class="st-chip font-mono">
                    {k.replace(/_/g, ' ')} {v}
                  </span>
                ))}
              </p>
            </section>
          );
        }}
      </SectionTabs>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div class="rounded-xl border border-line px-3 py-2">
      <dt class="text-xs text-ink-subtle">{label}</dt>
      <dd class="text-xl font-black tabular-nums">{value}</dd>
    </div>
  );
}
