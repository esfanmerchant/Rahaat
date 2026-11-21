import { useEffect, useRef } from 'preact/hooks';
import { Badge, humanize, num, Section, type CaseDetail, type DecisionTrace } from '../ui';

/**
 * Decision anatomy: how this decision was made, drawn from the trace the engine stored.
 * Every number comes from DecisionTrace (p_ok, thresholds, expected_costs, rule_trace) and from the application form
 * (provenance). Nothing is computed here beyond positions on the scale.
 */

const pctText = (v: number): string => `${(v * 100).toFixed(1)}%`;
const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));

/** p_ok on a 0 to 1 scale with the engine's own thresholds. The marker animates in (transform only). */
export function ProbabilityBar({ trace }: { trace: DecisionTrace }) {
  const track = useRef<HTMLDivElement>(null);
  const p = trace.p_ok === null ? null : clamp01(trace.p_ok);
  const approve = trace.thresholds['approve'];
  const reject = trace.thresholds['reject'];
  const floor = trace.thresholds['confidence_floor'];
  const rejectPos = reject === undefined ? undefined : clamp01(1 - reject);
  const inelig = trace.probabilities['p_ineligible'];

  useEffect(() => {
    const el = track.current;
    if (!el || p === null) return;
    const apply = () => el.style.setProperty('--tx', `${p * el.clientWidth}px`);
    apply();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(apply);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [p]);

  const zone = p === null || approve === undefined ? null : p >= approve ? 'approve zone' : rejectPos !== undefined && p <= rejectPos ? 'reject zone' : 'between the thresholds';
  const tick = (pos: number | undefined, label: string, sub: string, up: boolean) =>
    pos === undefined ? null : (
      <div key={label} class="st-tick" style={{ left: `${pos * 100}%` }} title={sub}>
        <span class={`absolute ${up ? 'bottom-full mb-1' : 'top-full mt-1'} -translate-x-1/2 whitespace-nowrap text-center text-xs leading-tight text-ink-muted`}>
          <span class="block font-semibold text-ink">{label}</span>
          <span class="rh-num font-mono">{sub}</span>
        </span>
      </div>
    );

  return (
    <div class="flex flex-col gap-1">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">How sure the system was (p_ok)</h3>
        {p === null ? (
          <span class="text-ink-subtle">No p_ok was stored for this decision.</span>
        ) : (
          <span class="rh-num font-mono text-lg font-black text-noor">
            {pctText(p)} <span class="text-xs font-normal text-ink-muted">{zone}</span>
          </span>
        )}
      </div>
      <div class="px-6 pb-10 pt-9">
        <div
          ref={track}
          class="st-prob"
          style={{ '--rej': `${(rejectPos ?? 0) * 100}%`, '--app': `${(approve ?? 1) * 100}%` }}
          role="img"
          aria-label={
            p === null
              ? 'Probability scale, no p_ok stored'
              : `p_ok ${pctText(p)} on a scale from 0 to 1. ${approve !== undefined ? `Approve threshold ${num(approve, 3)}. ` : ''}${floor !== undefined ? `Confidence floor ${num(floor, 3)}. ` : ''}${reject !== undefined ? `Reject threshold ${num(reject, 3)} on P(ineligible). ` : ''}`
          }
        >
          {tick(rejectPos, 'reject at or above', `P(ineligible) ${num(reject ?? 0, 3)}`, true)}
          {tick(floor, 'confidence floor', num(floor ?? 0, 3), false)}
          {tick(approve, 'approve at or above', num(approve ?? 0, 3), true)}
          {p !== null ? <div class="st-marker" /> : null}
        </div>
        <div class="rh-num mt-1 flex justify-between font-mono text-xs text-ink-subtle" aria-hidden="true">
          <span>0</span>
          <span>1</span>
        </div>
      </div>
      <p class="text-xs text-ink-subtle">
        The reject test reads P(ineligible){inelig !== undefined ? ` (${num(inelig, 3)} here)` : ''}, so its tick is drawn where p_ok can no longer exceed the complement. The route below is the engine's, not a reading of this picture.
      </p>
    </div>
  );
}

/** One bar per priced action; the cheapest is lit. The route is chosen by lowest expected cost, then guards. */
export function CostBars({ trace }: { trace: DecisionTrace }) {
  const costs = Object.entries(trace.expected_costs);
  if (costs.length === 0) return <p class="text-ink-subtle">No expected costs were stored.</p>;
  const max = Math.max(...costs.map(([, v]) => v), 0.0001);
  const lowest = costs.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
  return (
    <div class="flex flex-col gap-1">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Expected cost of each action (units)</h3>
      <ul class="flex flex-col gap-1.5">
        {costs
          .sort((a, b) => a[1] - b[1])
          .map(([k, v], i) => (
            <li key={k} class="grid grid-cols-[6.5rem_1fr_3.5rem] items-center gap-2">
              <span class={k === lowest ? 'font-semibold text-ink' : 'text-ink-muted'}>{humanize(k)}</span>
              <svg viewBox="0 0 100 10" preserveAspectRatio="none" class="h-2.5 w-full" role="img" aria-label={`${humanize(k)} costs ${num(v, 2)} units${k === lowest ? ', the lowest' : ''}`}>
                <rect width="100" height="10" rx="3" class="fill-sunken" />
                <rect
                  width={Math.max(2, (v / max) * 100)}
                  height="10"
                  rx="3"
                  class={`${k === lowest ? 'fill-primary' : 'fill-info-strong'} st-bar-fill`}
                  style={{ animationDelay: `${i * 90}ms` }}
                />
              </svg>
              <span class="rh-num text-end font-mono">{num(v, 2)}</span>
            </li>
          ))}
      </ul>
      <p class="text-xs text-ink-subtle">
        Lowest: <span class="font-semibold text-ink">{humanize(lowest)}</span>. The engine recorded route <span class="font-mono">{trace.route}</span> and outcome <span class="font-mono">{trace.outcome}</span>
        {trace.guards.length ? <>; guards that force a person: {trace.guards.map((g) => <Badge key={g} tone="warn">{humanize(g)}</Badge>)}</> : '.'}
      </p>
    </div>
  );
}

function TriGlyph({ result }: { result: 'pass' | 'fail' | 'unknown' }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" class="shrink-0">
      {result === 'pass' ? <path d="M2 6.5 5 9.5 10.5 3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /> : null}
      {result === 'fail' ? <path d="M2.5 2.5 9.5 9.5M9.5 2.5 2.5 9.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" /> : null}
      {result === 'unknown' ? (
        <>
          <path d="M4 4.4a2 2 0 1 1 2.9 1.8C6.3 6.5 6 6.8 6 7.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
          <circle cx="6" cy="10" r="1" fill="currentColor" />
        </>
      ) : null}
    </svg>
  );
}

/** Rule checks as tri-state chips: pass, fail or unknown. Unknown stays unknown; it is never rounded to pass. */
export function RuleChips({ trace }: { trace: DecisionTrace }) {
  const rules = trace.rule_trace;
  if (rules.length === 0) return <p class="text-ink-subtle">No rule was evaluated.</p>;
  const counts = { pass: 0, fail: 0, unknown: 0 };
  for (const r of rules) counts[r.result]++;
  return (
    <div class="flex flex-col gap-1.5">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Rule checks</h3>
        <span class="text-xs text-ink-subtle">
          {counts.pass} true, {counts.fail} false, {counts.unknown} unknown
        </span>
      </div>
      <ul class="flex flex-wrap gap-1.5">
        {rules.map((r, i) => {
          const tone = r.result === 'pass' ? 'ok' : r.result === 'fail' ? 'bad' : 'unk';
          const word = r.result === 'pass' ? 'true' : r.result === 'fail' ? 'false' : 'unknown';
          const values = Object.entries(r.values_used ?? {})
            .map(([k, v]) => `${k}: ${v === null || v === undefined ? 'unknown' : String(v)}`)
            .join('; ');
          return (
            <li
              key={r.rule_id}
              class={`st-chip ${tone} st-sweep`}
              style={{ animationDelay: `${i * 60}ms` }}
              title={`${r.label_en ?? r.rule_id}. ${r.hard ? 'Hard rule' : 'Soft rule'}. ${values}. Inputs ${r.verified_inputs ? 'verified' : 'not verified'}.`}
            >
              <TriGlyph result={r.result} />
              <span class="font-mono">{r.rule_id}</span>
              <span class="sr-only">{word}</span>
              {r.hard ? <span class="text-[0.65rem] uppercase tracking-wide opacity-80">hard</span> : null}
              {r.verified_inputs ? null : <span class="text-[0.65rem] uppercase tracking-wide opacity-80">unverified input</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type Prov = 'qr_signed' | 'registry' | 'spoken' | 'tapped' | 'typed' | 'ocr' | 'officer';
const PROV: Record<Prov, { label: string; tone: string; glyph: preact.JSX.Element }> = {
  qr_signed: {
    label: 'Signed QR',
    tone: 'ok',
    glyph: (
      <>
        <rect x="1.5" y="1.5" width="4" height="4" fill="none" stroke="currentColor" stroke-width="1.4" />
        <rect x="8.5" y="1.5" width="4" height="4" fill="none" stroke="currentColor" stroke-width="1.4" />
        <rect x="1.5" y="8.5" width="4" height="4" fill="none" stroke="currentColor" stroke-width="1.4" />
        <path d="M8.5 11 10.5 13 13 9.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
      </>
    ),
  },
  registry: {
    label: 'Registry',
    tone: 'ok',
    glyph: <path d="M2 11.5h10M3 11.5V6.5M7 11.5V6.5M11 11.5V6.5M1.5 6 7 2.5 12.5 6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />,
  },
  spoken: {
    label: 'Spoken',
    tone: 'warn',
    glyph: <path d="M7 1.8a2 2 0 0 0-2 2v3a2 2 0 0 0 4 0v-3a2 2 0 0 0-2-2ZM3 7a4 4 0 0 0 8 0M7 11v2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />,
  },
  tapped: {
    label: 'Tapped',
    tone: 'warn',
    glyph: <path d="M5.5 7V3.5a1.2 1.2 0 0 1 2.4 0V7l3 .8c.8.2 1.2.9 1 1.7l-.6 2.5H6.2L3.7 9.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" />,
  },
  typed: {
    label: 'Typed',
    tone: 'warn',
    glyph: <path d="M1.5 4h11v6.5h-11zM3.5 6.5h1M6.5 6.5h1M9.5 6.5h1M4 8.8h6" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />,
  },
  ocr: {
    label: 'Read from a photo',
    tone: 'warn',
    glyph: <path d="M1.5 4.5v-3h3M9.5 1.5h3v3M12.5 9.5v3h-3M4.5 12.5h-3v-3M3.5 7h7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />,
  },
  officer: {
    label: 'Officer',
    tone: 'info',
    glyph: <path d="M7 6.5a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6ZM2.5 13c0-2.6 2-4.2 4.5-4.2s4.5 1.6 4.5 4.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />,
  },
};

export function ProvBadge({ prov, verified }: { prov: string; verified?: boolean | undefined }) {
  const p = PROV[prov as Prov] ?? { label: prov, tone: '', glyph: <circle cx="7" cy="7" r="3" fill="none" stroke="currentColor" stroke-width="1.4" /> };
  return (
    <span class={`st-chip ${p.tone}`} title={`${p.label}${verified ? ', verified' : ', not verified'}`}>
      <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true">
        {p.glyph}
      </svg>
      {p.label}
    </span>
  );
}

/** Where each answer came from. Signed QR and registry are verified sources; tapped and spoken are the citizen's word. */
export function Provenance({ form }: { form: CaseDetail['form'] | undefined }) {
  if (!form) return null;
  const fields = Object.entries(form).filter(([k, v]) => typeof v === 'object' && v !== null && k !== 'language') as Array<[string, { provenance?: string; verified?: boolean; value?: unknown }]>;
  const by = new Map<string, string[]>();
  for (const [name, f] of fields) {
    const key = f.provenance ?? 'unknown';
    by.set(key, [...(by.get(key) ?? []), name]);
  }
  if (by.size === 0) return null;
  return (
    <div class="flex flex-col gap-1.5">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Evidence provenance</h3>
      <ul class="flex flex-col gap-1">
        {[...by.entries()].map(([prov, names]) => (
          <li key={prov} class="flex flex-wrap items-center gap-1.5">
            <span class="w-36 shrink-0">
              <ProvBadge prov={prov} verified={fields.find(([, f]) => f.provenance === prov)?.[1].verified} />
            </span>
            <span class="font-mono text-xs text-ink-muted">{names.join(', ')}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The whole panel: probability, costs, rule checks and provenance. */
export function DecisionAnatomy({ trace, form }: { trace: DecisionTrace; form?: CaseDetail['form'] | undefined }) {
  return (
    <Section id="anatomy" title="Decision anatomy" aside={<span class="font-mono text-xs text-ink-subtle">rule v{trace.rule_version_no} · {trace.model_version}</span>}>
      <div class="flex flex-col gap-5">
        <ProbabilityBar trace={trace} />
        <div class="grid gap-6 lg:grid-cols-2">
          <CostBars trace={trace} />
          <RuleChips trace={trace} />
        </div>
        {form ? <Provenance form={form} /> : null}
      </div>
    </Section>
  );
}
