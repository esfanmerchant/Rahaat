import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import type { Pulse } from '../../live/types';
import { HBars } from '../charts';
import { bucketize, Donut, HexLegend, HexMap, PROVINCES, provinceOf, QuietView, Sparkline, useQuiet, type HexRow, type Quiet, type Seg } from '../dash';
import type { components } from '../../shared/api/schema';
import { activeRole, labelText, PUNJAB_TILES, SINDH_TILES } from '../scam';
import { Section, fmtTime, pct } from '../ui';
import type { Tone } from '../charts';
import { CountUp } from '../viz';
import { DragGrid, resetLayouts, type DragItem } from '../DragGrid';
import { InfoTip } from '../InfoTip';
import { SectionTabs } from '../SectionTabs';

/**
 * The Command Center: the staff landing page. Every number comes from an endpoint that exists; a panel whose endpoint
 * refuses this role says so and shows nothing in its place. Everything refreshes quietly (pulse 15 s, stream 10 s).
 * Sub-sections are tabs (Live, Map & scams, System); tiles and panels can be reordered (DragGrid) and the order is remembered.
 */

const SINDH = new Set(SINDH_TILES.flat().filter((d): d is string => d !== null));
const PUNJAB = new Set(PUNJAB_TILES.flat().filter((d): d is string => d !== null));
type Analysis = components['schemas']['DecisionAnalysisOut'];

type Lane = 'approve' | 'ask' | 'human' | 'reject';
const laneOf = (d: { route: string; outcome: string }): Lane => (d.route === 'ask_more' ? 'ask' : d.route === 'human' ? 'human' : d.outcome === 'rejected' ? 'reject' : 'approve');
const LANE: Record<Lane, { label: string; tone: Tone }> = {
  approve: { label: 'auto', tone: 'ok' },
  ask: { label: 'proof', tone: 'warn' },
  human: { label: 'person', tone: 'info' },
  reject: { label: 'reject', tone: 'bad' },
};
const CHIP: Record<Tone, string> = { ok: 'ok', warn: 'warn', info: 'info', bad: 'bad', muted: '' };

const median = (xs: readonly number[]): number | null => {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? (s[m] as number) : ((s[m - 1] as number) + (s[m] as number)) / 2;
};

function Tile({
  id,
  label,
  tone,
  value,
  format,
  suffix,
  hint,
  spark,
  sparkLabel,
}: {
  id: string;
  label: string;
  tone: Tone;
  value: number;
  format?: (n: number) => string;
  suffix?: string;
  hint: string;
  spark?: { values: number[]; window: string } | null;
  sparkLabel: string;
}) {
  return (
    <div class={`st-tile st-tone-${tone} flex min-w-0 flex-col gap-1 p-3`} data-testid={`tile-${id}`} title={spark ? `${hint}, last ${spark.window}` : hint}>
      <p class="text-xs font-bold uppercase tracking-widest text-ink-muted">{label}</p>
      <p class="st-tile-num rh-num flex items-baseline gap-1 text-3xl font-black leading-none tracking-tight 2xl:text-4xl">
        <CountUp value={value} ms={1100} {...(format ? { format } : {})} />
        {suffix ? <span class="text-base font-bold text-ink-muted">{suffix}</span> : null}
      </p>
      <div class="mt-1 min-h-[34px]">{spark ? <Sparkline values={spark.values} tone={tone} label={sparkLabel} /> : <span class="text-xs text-ink-subtle">no history</span>}</div>
      <p class="truncate text-xs text-ink-subtle">{hint}</p>
    </div>
  );
}

export function OverviewPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = activeRole();
  const dept = session.value.status === 'signed-in' ? session.value.active.tenant_name : '';

  const [pulse, reloadPulse] = useQuiet(() => call(api.GET('/v1/public/pulse')), 15000);
  const [decisions, reloadDecisions] = useQuiet(() => call(api.GET('/v1/decisions', { params: { query: { limit: 100 } } })), 10000);
  const [payments, reloadPayments] = useQuiet(() => call(api.GET('/v1/payments', { params: { query: { limit: 100 } } })), 30000);
  const [trends] = useQuiet(() => call(api.GET('/v1/scam/trends', { params: { query: { days: 7 } } })), 60000);
  const [smap, reloadMap] = useQuiet(() => call(api.GET('/v1/scam/map', { params: { query: { days: 30 } } })), 60000);
  const [camps, reloadCamps] = useQuiet(() => call(api.GET('/v1/scam/campaigns', { params: { query: { days: 7, limit: 8 } } })), 60000);
  const [evals, reloadEvals] = useQuiet(() => call(api.GET('/v1/evals/decisions/latest')), 120000);
  const [health, reloadHealth] = useQuiet(() => call(api.GET('/v1/system/health')), 30000);
  const [jobs, reloadJobs] = useQuiet(() => call(api.GET('/v1/admin/jobs', { params: { query: { limit: 100 } } })), 30000);
  const [chain, reloadChain] = useQuiet(() => call(api.GET('/v1/audit/verify')), 60000);

  const items = decisions.state === 'ok' ? decisions.data.items : null;
  const p: Pulse | null = pulse.state === 'ok' ? pulse.data : null;
  const routes = p?.live.decisions_by_route;
  const rt = (k: string): number => routes?.[k] ?? 0;
  const routeTotal = rt('auto') + rt('ask_more') + rt('human') + rt('reject');
  const appTotal = p ? Object.values(p.live.applications_by_status).reduce((a, b) => a + b, 0) : 0;

  const sparks = useMemo(() => {
    const out: Record<string, { values: number[]; window: string } | null> = { apps: null, auto: null, human: null, paid: null, scams: null };
    if (items) {
      out['apps'] = bucketize(items.map((d) => ({ at: d.decided_at })));
      out['auto'] = bucketize(items.filter((d) => laneOf(d) === 'approve').map((d) => ({ at: d.decided_at })));
      out['human'] = bucketize(items.filter((d) => d.route === 'human').map((d) => ({ at: d.decided_at })));
    }
    if (payments.state === 'ok') out['paid'] = bucketize(payments.data.items.filter((x) => x.status === 'settled').map((x) => ({ at: x.created_at, w: x.amount_pkr })));
    if (trends.state === 'ok') out['scams'] = { values: trends.data.total.map((x) => x.count ?? 0), window: `${trends.data.days} d` };
    return out;
  }, [items, payments, trends]);

  const latencies = items ? items.map((d) => d.latency_ms).filter((x): x is number => typeof x === 'number') : [];
  const med = median(latencies);

  const refreshAll = (): void => {
    reloadPulse();
    reloadDecisions();
    reloadPayments();
    reloadMap();
    reloadCamps();
    reloadEvals();
    reloadHealth();
    reloadJobs();
    reloadChain();
  };

  const kpis: DragItem[] = [
    { id: 'applications', label: 'Applications', node: <Tile id="applications" label="Applications" tone="info" value={appTotal} hint="All statuses" spark={sparks['apps'] ?? null} sparkLabel="Decisions per bucket" /> },
    {
      id: 'auto',
      label: 'Auto decided',
      node: (
        <Tile
          id="auto"
          label="Auto decided"
          tone="ok"
          value={routeTotal > 0 ? Math.round((rt('auto') / routeTotal) * 100) : 0}
          suffix="%"
          hint={`${rt('auto')} of ${routeTotal}`}
          spark={sparks['auto'] ?? null}
          sparkLabel="Automatic approvals per bucket"
        />
      ),
    },
    { id: 'human', label: 'To a person', node: <Tile id="human" label="To a person" tone="info" value={rt('human')} hint="With briefing" spark={sparks['human'] ?? null} sparkLabel="Handoffs per bucket" /> },
    {
      id: 'paid',
      label: 'Paid',
      node: (
        <Tile id="paid" label="Paid (mock)" tone="ok" value={p?.live.payments.settled_amount_pkr ?? 0} suffix="PKR" hint={`${p?.live.payments.settled ?? 0} settled`} spark={sparks['paid'] ?? null} sparkLabel="Rupees settled per bucket" />
      ),
    },
    {
      id: 'scams',
      label: 'Scams blocked',
      node: <Tile id="scams" label="Scams blocked" tone="bad" value={p?.live.scam.blocked ?? 0} hint={`${p?.live.scam.reports ?? 0} reports`} spark={sparks['scams'] ?? null} sparkLabel="Scam reports per day" />,
    },
    {
      id: 'median',
      label: med !== null ? 'Median time' : 'Audit entries',
      node:
        med !== null ? (
          <Tile
            id="median"
            label="Median time"
            tone="warn"
            value={med}
            suffix="ms"
            hint={`${latencies.length} decisions`}
            spark={items ? { values: latencies.slice(0, 30).reverse(), window: `${Math.min(30, latencies.length)} decisions` } : null}
            sparkLabel="Engine time per decision"
          />
        ) : (
          <Tile id="chain" label="Audit entries" tone="warn" value={p?.live.audit_chain_length ?? 0} hint="Hash-chained" spark={null} sparkLabel="Audit entries" />
        ),
    },
  ];

  const livePanels: DragItem[] = [
    {
      id: 'stream',
      label: 'Decision stream',
      node: (
        <Section id="stream-h" title="Decision stream" aside={<span class="text-xs text-ink-subtle">every 10 s</span>}>
          <QuietView q={decisions} reload={reloadDecisions} what="the decision stream (auditors and officers read it)" rows={6}>
            {(d) => <Stream items={d.items} />}
          </QuietView>
        </Section>
      ),
    },
    {
      id: 'mix',
      label: 'Decision mix',
      node: (
        <Section id="mix-h" title="Decision mix" aside={<InfoTip text="Reject means a hard rule failed on verified input. Everything the system is unsure about goes to proof or to a person." />}>
          <QuietView q={pulse} reload={reloadPulse} what="the decision mix" rows={4}>
            {(d) => {
              const r = d.live.decisions_by_route;
              const segs: Seg[] = [
                { key: 'auto', label: 'Auto', value: r['auto'] ?? 0, tone: 'ok' },
                { key: 'ask_more', label: 'Proof', value: r['ask_more'] ?? 0, tone: 'warn' },
                { key: 'human', label: 'Person', value: r['human'] ?? 0, tone: 'info' },
                { key: 'reject', label: 'Reject', value: r['reject'] ?? 0, tone: 'bad' },
              ];
              return <Donut segs={segs} centreLabel="decisions" id="mix" />;
            }}
          </QuietView>
        </Section>
      ),
    },
  ];

  const mapPanels: DragItem[] = [
    {
      id: 'map',
      label: 'Scam map',
      node: (
        <Section id="map-h" title="Scam map" aside={<span class="text-xs text-ink-subtle">30 days</span>}>
          <QuietView q={smap} reload={reloadMap} what="the scam map" rows={5}>
            {(m) => <MapBody totals={m.district_totals} hidden={m.hidden['district_totals'] ?? 0} k={m.k} />}
          </QuietView>
        </Section>
      ),
    },
    {
      id: 'radar',
      label: 'Scam radar',
      node: (
        <Section id="radar-h" title="Scam radar" aside={<InfoTip text="Messages per cluster of near-identical text, last 7 days. Every bar is a lower bound." />}>
          <QuietView q={camps} reload={reloadCamps} what="scam campaigns" rows={5}>
            {(c) =>
              c.items.length === 0 ? (
                <p class="text-ink-muted">No campaigns.</p>
              ) : (
                <HBars rows={c.items.slice(0, 7).map((x) => ({ label: `${labelText(x.label)}: ${x.hosts[0] ?? x.sample_text.slice(0, 24)}`, value: x.size_in_window, cls: 'fill-danger' }))} />
              )
            }
          </QuietView>
        </Section>
      ),
    },
  ];

  const systemPanels: DragItem[] = [
    {
      id: 'health',
      label: 'System health',
      node: (
        <Section
          id="health-h"
          title="System health"
          aside={
            <a href="/staff/health" class="text-xs">
              Details
            </a>
          }
        >
          <HealthStrip health={health} reloadHealth={reloadHealth} jobs={jobs} reloadJobs={reloadJobs} chain={chain} reloadChain={reloadChain} pulse={p} />
        </Section>
      ),
    },
    {
      id: 'cost',
      label: 'Cost of errors',
      node: (
        <Section
          id="cost-h"
          title="Cost of errors"
          aside={
            <a href="/staff/costs" class="text-xs">
              Details
            </a>
          }
        >
          <CostBody pulse={pulse} evals={evals} reloadPulse={reloadPulse} />
        </Section>
      ),
    },
  ];

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-xl font-black tracking-tight">
          Command Center
        </h1>
        <InfoTip
          label="About this page"
          text={`${p?.notice ?? 'Prototype. Not an official service.'} The live system${dept ? `, ${dept}` : ''}, as ${role || 'staff'}. Updates by itself.${p ? ` Pulse ${fmtTime(p.generated_at)}.` : ''}`}
        />
        <span class="ms-auto flex gap-2">
          <button type="button" class="cc-btn" onClick={() => resetLayouts()}>
            Reset layout
          </button>
          <button type="button" class="cc-btn" onClick={refreshAll}>
            Refresh
          </button>
        </span>
      </div>

      <SectionTabs
        label="Command Center"
        sections={[
          { id: 'live', label: 'Live' },
          { id: 'map', label: 'Map & scams' },
          { id: 'system', label: 'System' },
        ]}
      >
        {(tab) =>
          tab === 'live' ? (
            <div class="flex flex-col gap-3">
              {pulse.state !== 'ok' ? (
                <QuietView q={pulse} reload={reloadPulse} what="the live counters" rows={2}>
                  {() => null}
                </QuietView>
              ) : (
                <DragGrid id="cc-kpis" class="cc-grid-kpi" items={kpis} />
              )}
              <DragGrid id="cc-live" class="cc-grid-2" items={livePanels} />
            </div>
          ) : tab === 'map' ? (
            <DragGrid id="cc-map" class="cc-grid-2" items={mapPanels} />
          ) : (
            <DragGrid id="cc-system" class="cc-grid-2" items={systemPanels} />
          )
        }
      </SectionTabs>
    </section>
  );
}

function Stream({ items: rows }: { items: readonly StreamRow[] }) {
  const seen = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const ids = new Set(rows.map((r) => r.id));
    if (seen.current) {
      const added = rows.filter((r) => !seen.current!.has(r.id)).map((r) => r.id);
      if (added.length) {
        setFresh(new Set(added));
        const t = window.setTimeout(() => setFresh(new Set()), 4000);
        seen.current = ids;
        return () => window.clearTimeout(t);
      }
    }
    seen.current = ids;
    return undefined;
  }, [rows]);
  if (rows.length === 0) return <p class="text-ink-muted">No decisions yet.</p>;
  return (
    <div class="cc-scroll">
      <table class="st-table w-full border-collapse text-sm">
        <caption class="sr-only">Most recent decisions, newest first</caption>
        <thead>
          <tr>
            {['Time', 'Route', 'Outcome', 'p_ok'].map((h) => (
              <th key={h} scope="col" class="border-b border-line-strong px-2 py-1.5 text-start text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((d, i) => {
            const lane = laneOf(d);
            const l = LANE[lane];
            return (
              <tr key={d.id} class={`hover:bg-surface ${fresh.has(d.id) ? 'st-slide-new' : 'st-row-in'}`} style={{ '--i': i }}>
                <td class="border-b border-line px-2 py-1 font-mono text-xs tabular-nums">
                  <a href={`/staff/decisions/${d.id}`}>{fmtTime(d.decided_at).slice(11, 19)}</a>
                </td>
                <td class="border-b border-line px-2 py-1">
                  <span class={`st-chip ${CHIP[l.tone]}`}>{l.label}</span>
                </td>
                <td class="border-b border-line px-2 py-1">{d.outcome.replace(/_/g, ' ')}</td>
                <td class="border-b border-line px-2 py-1">
                  <span class={`inline-flex items-center gap-2 st-tone-${l.tone}`}>
                    <span class="st-track" role="img" aria-label={`p_ok ${pct(d.p_ok)}`}>
                      <i style={{ width: `${Math.round((d.p_ok ?? 0) * 100)}%` }} />
                    </span>
                    <span class="font-mono text-xs tabular-nums">{d.p_ok == null ? 'n/a' : d.p_ok.toFixed(3)}</span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface StreamRow {
  id: string;
  decided_at: string;
  route: string;
  outcome: string;
  p_ok?: number | null;
}

function MapBody({ totals, hidden, k }: { totals: readonly { district: string; count: number }[]; hidden: number; k: number }) {
  const { rows, unmapped } = useMemo(() => {
    const by = new Map<string, { count: number; d: { district: string; count: number }[] }>();
    let un = 0;
    for (const t of totals) {
      const key = provinceOf(t.district, SINDH, PUNJAB);
      if (!key) {
        un += t.count;
        continue;
      }
      const e = by.get(key) ?? { count: 0, d: [] };
      e.count += t.count;
      e.d.push(t);
      by.set(key, e);
    }
    const r: HexRow[] = PROVINCES.map((province) => {
      const e = by.get(province.key);
      return { province, count: e?.count ?? 0, top: (e?.d ?? []).sort((a, b) => b.count - a.count) };
    });
    return { rows: r, unmapped: un };
  }, [totals]);
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div class="flex flex-col gap-2">
      <span class="self-end">
        <InfoTip
          text={`Reports are placed by district; provinces with none are drawn empty, not estimated.${unmapped > 0 ? ` ${unmapped} reports are in districts this map cannot place.` : ''}${hidden > 0 ? ` ${hidden} districts under ${k} reports are hidden.` : ''}`}
        />
      </span>
      <HexMap rows={rows} unit="scam reports" />
      <HexLegend max={max} unit="scam reports" />
    </div>
  );
}

function CostBody({ pulse, evals, reloadPulse }: { pulse: Quiet<Pulse>; evals: Quiet<Analysis>; reloadPulse: () => void }) {
  const ev = evals.state === 'ok' ? evals.data.operating_point : null;
  return (
    <QuietView q={pulse} reload={reloadPulse} what="the replay headline" rows={4}>
      {(d) => {
        const hl = d.replay.headline;
        if (!hl) return <p class="text-ink-muted">No replay here.</p>;
        const baseline = ev ? ev.cost_per_case + ev.saving_per_case : null;
        return (
          <div class="flex flex-col gap-3">
            <dl class="grid grid-cols-3 gap-2 text-center">
              {[
                { l: 'Wrong approvals', v: hl.wrong_approvals, t: 'bad' as Tone },
                { l: 'Wrong rejections', v: hl.wrong_rejections, t: 'warn' as Tone },
                { l: 'Silent guesses', v: hl.silent_guesses, t: 'ok' as Tone },
              ].map((x) => (
                <div key={x.l} class={`st-tile st-tone-${x.t} px-1 py-2`}>
                  <dd class="st-tile-num rh-num text-3xl font-black leading-none">
                    <CountUp value={x.v} />
                  </dd>
                  <dt class="mt-1 text-[11px] uppercase tracking-wide text-ink-muted">{x.l}</dt>
                </div>
              ))}
            </dl>
            {ev && baseline !== null ? (
              <div class="st-chart flex flex-col gap-1.5" data-testid="cost-bars">
                <p class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Cost per case
                  <InfoTip
                    text={`Replay of ${hl.cases.toLocaleString('en-US')} labelled cases (${d.replay.replay_source}): ${hl.approved} approved, ${hl.rejected} rejected by a hard rule, ${hl.asked_for_proof} asked for proof, ${hl.sent_to_person} sent to a person. Saving ${ev.saving_per_case.toFixed(2)} per case on ${ev.n} held-out cases.`}
                  />
                </p>
                <HBars
                  rows={[
                    { label: 'Rahat', value: Number(ev.cost_per_case.toFixed(2)), cls: 'fill-primary' },
                    { label: 'All to a person', value: Number(baseline.toFixed(2)), cls: 'fill-danger' },
                  ]}
                  max={Math.max(baseline, ev.cost_per_case)}
                />
              </div>
            ) : (
              <p class="text-xs text-ink-subtle">Cost per case needs the evaluation endpoint.</p>
            )}
          </div>
        );
      }}
    </QuietView>
  );
}

function HealthStrip({
  health,
  reloadHealth,
  jobs,
  reloadJobs,
  chain,
  reloadChain,
  pulse,
}: {
  health: Quiet<unknown>;
  reloadHealth: () => void;
  jobs: Quiet<unknown>;
  reloadJobs: () => void;
  chain: Quiet<unknown>;
  reloadChain: () => void;
  pulse: Pulse | null;
}) {
  type H = { database?: string; providers?: Record<string, unknown> };
  const h = health.state === 'ok' ? (health.data as H) : null;
  const providers = h?.providers ?? {};
  const voice = (providers['voice'] ?? {}) as Record<string, string>;
  const ocrEngine = String(providers['ocr_engine'] ?? 'unknown');
  const ocrOk = providers[`ocr_${ocrEngine}`] === 'available' || providers['ocr_engine'] !== undefined;
  const stt = voice['stt_server'] ?? 'unknown';
  const jobItems = jobs.state === 'ok' ? (jobs.data as { items: { status: string }[] }).items : null;
  const queued = jobItems?.filter((j) => j.status === 'queued' || j.status === 'running').length ?? 0;
  const failed = jobItems?.filter((j) => j.status === 'failed' || j.status === 'dead').length ?? 0;
  const ch = chain.state === 'ok' ? (chain.data as { ok: boolean; checked: number; first_broken_seq?: number | null }) : null;

  const Cell = ({ label, tone, value, note }: { label: string; tone: Tone; value: string; note: string }) => (
    <li class={`st-tone-${tone} flex min-w-0 items-center gap-2.5 rounded-lg border border-line px-3 py-2`}>
      <span class="st-swatch" aria-hidden="true" />
      <div class="min-w-0">
        <p class="text-xs uppercase tracking-wider text-ink-subtle">{label}</p>
        <p class="truncate font-semibold">{value}</p>
        <p class="truncate text-xs text-ink-muted" title={note}>
          {note}
        </p>
      </div>
    </li>
  );
  const denied = (q: Quiet<unknown>): boolean => q.state === 'fail' && q.failure.kind === 'forbidden';
  return (
    <ul class="grid grid-cols-2 gap-2">
      {h ? (
        <Cell label="Database" tone={h.database === 'ok' ? 'ok' : 'bad'} value={h.database ?? 'unknown'} note="Postgres, RLS" />
      ) : (
        <li class="rounded-lg border border-line px-3 py-2">
          <p class="text-xs uppercase tracking-wider text-ink-subtle">Database</p>
          <QuietView q={health} reload={reloadHealth} what="system health" rows={1}>
            {() => null}
          </QuietView>
        </li>
      )}
      {jobItems ? (
        <Cell label="Job queue" tone={failed > 0 ? 'bad' : queued > 5 ? 'warn' : 'ok'} value={`${queued} wait, ${failed} failed`} note={`${jobItems.length} recent`} />
      ) : (
        <li class="rounded-lg border border-line px-3 py-2">
          <p class="text-xs uppercase tracking-wider text-ink-subtle">Job queue</p>
          <QuietView q={jobs} reload={reloadJobs} what="the job queue" rows={1}>
            {() => null}
          </QuietView>
        </li>
      )}
      {h ? <Cell label="OCR" tone={ocrOk ? 'ok' : 'warn'} value={ocrEngine} note={providers['ocr_tesseract'] === 'missing' ? 'not installed' : 'local'} /> : null}
      {h ? <Cell label="Speech" tone={stt === 'unknown' ? 'warn' : 'ok'} value={stt.replace(/_/g, ' ')} note={`whisper ${String(voice['stt_local_whisper'] ?? 'unknown').replace(/_/g, ' ')}`} /> : null}
      {ch ? (
        <Cell label="Audit chain" tone={ch.ok ? 'ok' : 'bad'} value={ch.ok ? 'verified' : `broken at ${ch.first_broken_seq ?? '?'}`} note={`${ch.checked} checked`} />
      ) : denied(chain) ? (
        <Cell label="Audit chain" tone="ok" value={`${pulse?.live.audit_chain_length ?? 'n/a'} entries`} note="no verify access" />
      ) : (
        <li class="rounded-lg border border-line px-3 py-2">
          <p class="text-xs uppercase tracking-wider text-ink-subtle">Audit chain</p>
          <QuietView q={chain} reload={reloadChain} what="the audit chain" rows={1}>
            {() => null}
          </QuietView>
        </li>
      )}
    </ul>
  );
}
