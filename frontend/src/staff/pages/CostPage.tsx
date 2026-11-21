import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Confusion, ReliabilityChart, XYChart } from '../charts';
import { BTN, BTN_PRIMARY, flashFail, FlashLine, MIN_REASON, type Flash } from '../kit';
import { activeRole } from '../scam';
import { INPUT, Section, useLoad } from '../ui';

type Analysis = components['schemas']['DecisionAnalysisOut'];
type Costs = components['schemas']['CostMatrix'];

interface Knob {
  key: keyof Costs;
  label: string;
  hint: string;
  min: number;
  max: number;
  step: number;
}

const KNOBS: readonly Knob[] = [
  { key: 'wrong_approve', label: 'Wrong approval', hint: 'Paying someone who should not be paid.', min: 5, max: 500, step: 5 },
  { key: 'wrong_reject', label: 'Wrong rejection', hint: 'Turning away someone who should be paid.', min: 5, max: 300, step: 5 },
  { key: 'human_review', label: 'Human review', hint: 'An officer looks at the case.', min: 0.5, max: 30, step: 0.5 },
  { key: 'ask_proof', label: 'Ask for proof', hint: 'The citizen is asked for one more document.', min: 0, max: 10, step: 0.1 },
  { key: 'delay_per_day', label: 'Delay per day', hint: 'Each day a person waits in the queue.', min: 0, max: 2, step: 0.05 },
];

const same = (a: Costs, b: Costs): boolean => KNOBS.every((k) => Math.abs(a[k.key] - b[k.key]) < 1e-9);
const rs = (units: number): string => `${units.toFixed(2)}`;

/** Debounced what-if: every slider move recomputes the analysis on the server; nothing is stored. */
function useWhatIf(base: Analysis | null, costs: Costs | null) {
  const [live, setLive] = useState<{ status: 'idle' | 'busy' | 'ok' | 'fail'; data?: Analysis; failure?: Parameters<typeof FailureState>[0]['failure'] }>({ status: 'idle' });
  const seq = useRef(0);
  useEffect(() => {
    if (!costs || !base) return;
    if (same(costs, base.costs)) {
      setLive({ status: 'idle' });
      return;
    }
    const mine = ++seq.current;
    setLive((s) => ({ ...s, status: 'busy' }));
    const timer = window.setTimeout(() => {
      void call(api.POST('/v1/evals/decisions/what-if', { body: costs })).then((res) => {
        if (mine !== seq.current) return;
        setLive(res.ok ? { status: 'ok', data: res.data } : { status: 'fail', failure: res.failure });
      });
    }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [costs?.wrong_approve, costs?.wrong_reject, costs?.human_review, costs?.ask_proof, costs?.delay_per_day, base]);
  return live;
}

/** Cost of being wrong: the five costs, the thresholds they give, and what that does on 1,000+ held-out labelled cases. */
export function CostPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const admin = activeRole() === 'admin';
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/evals/decisions/latest')), []);
  const [costs, setCosts] = useState<Costs | null>(null);
  const base = loaded.state === 'ok' ? loaded.data : null;
  useEffect(() => {
    if (base) setCosts(base.costs);
  }, [base]);
  const live = useWhatIf(base, costs);
  const shown: Analysis | null = live.status === 'ok' && live.data ? live.data : base;
  const dirty = base !== null && costs !== null && !same(costs, base.costs);

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-baseline gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Cost of being wrong
        </h1>
        <span class="text-xs text-ink-subtle">Costs are in units; one unit is about Rs 120. The engine approves alone only when a wrong approval is worth the risk.</span>
      </div>
      {loaded.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Scoring the held-out cases…" /> : null}
      {loaded.state === 'fail' ? <FailureState failure={loaded.failure} density="staff" onRetry={reload} /> : null}
      {base && costs && shown ? (
        <div class="grid items-start gap-4 xl:grid-cols-[22rem_1fr]">
          <div class="flex flex-col gap-3">
            <Section id="knobs" title="The five costs">
              <Sliders costs={costs} saved={base.costs} onChange={setCosts} />
              <p class="mt-2 text-xs text-ink-subtle" aria-live="polite">
                {live.status === 'busy' ? 'Recomputing on the server…' : dirty ? 'Showing your unsaved costs. Nothing is stored until an admin saves.' : 'Showing the saved costs.'}
              </p>
              {live.status === 'fail' && live.failure ? <FailureState failure={live.failure} density="staff" heading="h2" /> : null}
            </Section>
            <Section id="save" title="Save">
              {admin ? (
                <SaveBox costs={costs} disabled={!dirty} onSaved={() => reload()} onReset={() => setCosts(base.costs)} />
              ) : (
                <p class="text-ink-muted">Only an admin can save new costs. You can move the sliders to see what they would do; nothing is stored.</p>
              )}
            </Section>
          </div>
          <div class="flex flex-col gap-3">
            <Headline a={shown} saved={base} dirty={dirty} />
            <Section id="why" title="What the numbers say">
              <p class="max-w-4xl" data-testid="explanation">
                {shown.explanation}
              </p>
            </Section>
            <div class="grid gap-4 2xl:grid-cols-2">
              <Section id="curve" title="Expected cost against threshold">
                <CurveChart a={shown} />
              </Section>
              <Section id="rel" title="Can the confidence be trusted">
                <ReliabilityChart id="rel-chart" bins={shown.reliability.bins} ece={shown.reliability.ece} brier={shown.reliability.brier} n={shown.reliability.n} />
              </Section>
              <Section id="roc" title="ROC">
                <RocChart a={shown} />
              </Section>
              <Section id="pr" title="Precision and recall">
                <PrChart a={shown} />
              </Section>
            </div>
            <Section id="conf" title="Confusion matrix at the operating point">
              <Confusion rows={shown.confusion.rows} columns={shown.confusion.columns} counts={shown.confusion.counts} />
              <p class="mt-1 text-xs text-ink-subtle">Red cells are mistakes. Cases that went to a person or to proof are not mistakes, they cost review time.</p>
            </Section>
            <p class="text-xs text-ink-subtle">
              {shown.dataset.name}: {shown.dataset.cases} cases, {shown.dataset.persons} people, seed {shown.dataset.seed}, held out from training and calibration. {shown.dataset.note} Model {shown.model_version}, rule version {shown.rule_version_no ?? 'n/a'}.
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Sliders({ costs, saved, onChange }: { costs: Costs; saved: Costs; onChange: (c: Costs) => void }) {
  return (
    <div class="flex flex-col gap-3">
      {KNOBS.map((k) => {
        const id = `knob-${k.key}`;
        const v = costs[k.key];
        const changed = Math.abs(v - saved[k.key]) > 1e-9;
        return (
          <div key={k.key} class="flex flex-col gap-0.5">
            <div class="flex items-center justify-between gap-2">
              <label for={id} class="font-semibold">
                {k.label}
              </label>
              <input
                class={`${INPUT} w-20 text-end font-mono`}
                type="number"
                min={k.min}
                max={k.max * 2}
                step={k.step}
                value={v}
                aria-label={`${k.label} (number)`}
                onInput={(e) => {
                  const n = Number(e.currentTarget.value);
                  if (Number.isFinite(n) && (k.min === 0 ? n >= 0 : n > 0)) onChange({ ...costs, [k.key]: n });
                }}
              />
            </div>
            <input id={id} type="range" class="w-full" min={k.min} max={k.max} step={k.step} value={Math.min(k.max, v)} onInput={(e) => onChange({ ...costs, [k.key]: Number(e.currentTarget.value) })} aria-describedby={`${id}-h`} />
            <span id={`${id}-h`} class="text-xs text-ink-subtle">
              {k.hint} Saved: {saved[k.key]}
              {changed ? ' (changed)' : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SaveBox({ costs, disabled, onSaved, onReset }: { costs: Costs; disabled: boolean; onSaved: () => void; onReset: () => void }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const ok = !disabled && reason.trim().length >= MIN_REASON;
  const save = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.PUT('/v1/cost-matrix', { body: { ...costs, reason: reason.trim() } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: `Saved. The approve threshold is now ${res.data.thresholds.approve}. The next decision uses these costs. The change is in the audit log.` });
    setReason('');
    onSaved();
  };
  return (
    <form
      class="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) void save();
      }}
    >
      <label class="flex flex-col gap-1">
        Reason (audit log, at least {MIN_REASON} characters)
        <input class={INPUT} value={reason} maxLength={500} onInput={(e) => setReason(e.currentTarget.value)} />
      </label>
      <div class="flex gap-2">
        <button type="submit" class={BTN_PRIMARY} disabled={!ok || busy}>
          {busy ? 'Saving…' : 'Save costs'}
        </button>
        <button type="button" class={BTN} disabled={disabled} onClick={onReset}>
          Reset to saved
        </button>
      </div>
      <FlashLine flash={flash} />
    </form>
  );
}

function Delta({ now, was, bad = 'up', digits = 0, suffix = '' }: { now: number; was: number; bad?: 'up' | 'down'; digits?: number; suffix?: string }) {
  const d = now - was;
  if (Math.abs(d) < 10 ** -(digits + 1)) return <span class="text-xs text-ink-subtle">no change</span>;
  const worse = bad === 'up' ? d > 0 : d < 0;
  return (
    <span class={`text-xs ${worse ? 'text-danger' : 'text-primary-strong'}`}>
      {d > 0 ? '+' : ''}
      {d.toFixed(digits)}
      {suffix} {worse ? 'worse' : 'better'}
    </span>
  );
}

function Headline({ a, saved, dirty }: { a: Analysis; saved: Analysis; dirty: boolean }) {
  const op = a.operating_point;
  const was = saved.operating_point;
  const tile = (label: string, value: string, extra?: unknown, tid?: string) => (
    <div class="border border-line px-2 py-1">
      <dt class="text-xs text-ink-subtle">{label}</dt>
      <dd class="text-lg font-semibold tabular-nums" data-testid={tid}>
        {value}
      </dd>
      {dirty ? <div>{extra as never}</div> : null}
    </div>
  );
  return (
    <dl class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
      {tile('Approve alone when p_ok at least', a.thresholds.approve.toFixed(3), <Delta now={a.thresholds.approve} was={saved.thresholds.approve} bad="down" digits={3} />, 'threshold')}
      {tile('Measured best threshold', a.best_threshold.threshold.toFixed(2), <Delta now={a.best_threshold.threshold} was={saved.best_threshold.threshold} digits={2} bad="up" />, 'best-threshold')}
      {tile('Cost per case', rs(op.cost_per_case), <Delta now={op.cost_per_case} was={was.cost_per_case} digits={2} />)}
      {tile('Auto rate', `${(op.auto_rate * 100).toFixed(1)}%`, <Delta now={op.auto_rate * 100} was={was.auto_rate * 100} bad="down" digits={1} suffix=" pts" />)}
      {tile('False approvals', `${op.false_approvals} (${(op.false_approve_rate * 100).toFixed(2)}%)`, <Delta now={op.false_approvals} was={was.false_approvals} />, 'false-approvals')}
      {tile('False rejections', `${op.false_rejections} (${(op.false_reject_rate * 100).toFixed(2)}%)`, <Delta now={op.false_rejections} was={was.false_rejections} />)}
      {tile('Saving against all-human', `${rs(op.saving_per_case)} per case`)}
      {tile('Needs a person', `${op.needs_human} of ${op.n}`, <Delta now={op.needs_human} was={was.needs_human} />)}
      {tile('Asks for proof', String(op.needs_proof))}
      {tile('Unnecessary handoffs', String(op.unnecessary_handoffs))}
      {tile('Silent guesses', String(op.silent_guesses))}
      {tile('ROC AUC', a.roc_auc == null ? 'n/a' : a.roc_auc.toFixed(3))}
    </dl>
  );
}

function CurveChart({ a }: { a: Analysis }) {
  const pts = a.cost_curve.map((p) => [p.threshold, p.cost_per_case] as const);
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(...pts.map((p) => p[0]));
  const hi = Math.max(...pts.map((p) => p[0]));
  const top = Math.max(0.1, ...ys) * 1.05;
  const derived = a.thresholds.approve;
  const best = a.best_threshold;
  return (
    <XYChart
      id="cost-curve"
      title="Cost per case if auto-approval starts at this p_ok"
      xLabel="Approve threshold (p_ok)"
      yLabel="Cost per case (units)"
      xDomain={[lo, hi]}
      yDomain={[0, top]}
      series={[{ name: 'Cost per case', points: pts, stroke: 'stroke-info-strong', step: true }]}
      vlines={[
        { x: derived, label: `derived ${derived.toFixed(3)}`, stroke: 'stroke-primary', row: 0 },
        { x: best.threshold, label: `measured best ${best.threshold.toFixed(2)}`, stroke: 'stroke-warning-ink', row: 1 },
      ]}
      dots={[{ x: best.threshold, y: best.cost_per_case, label: `best on this data: ${best.cost_per_case.toFixed(3)}`, fill: 'fill-warning stroke-warning-ink' }]}
      summary={`Cost per case against the approve threshold. The threshold derived from the costs is ${derived.toFixed(3)}. The cheapest threshold measured on the held-out cases is ${best.threshold.toFixed(2)}, at ${best.cost_per_case.toFixed(3)} units per case.`}
    />
  );
}

function nearest<T extends { threshold: number }>(pts: readonly T[], t: number): T | undefined {
  return pts.reduce<T | undefined>((m, p) => (m === undefined || Math.abs(p.threshold - t) < Math.abs(m.threshold - t) ? p : m), undefined);
}

function RocChart({ a }: { a: Analysis }) {
  const at = nearest(a.roc, a.thresholds.approve);
  return (
    <XYChart
      id="roc-chart"
      title={`ROC (AUC ${a.roc_auc == null ? 'n/a' : a.roc_auc.toFixed(3)})`}
      xLabel="False positive rate"
      yLabel="True positive rate"
      xDomain={[0, 1]}
      yDomain={[0, 1]}
      diagonal
      series={[{ name: 'Model', points: a.roc.map((p) => [p.fpr, p.tpr] as const), stroke: 'stroke-info-strong' }]}
      dots={at ? [{ x: at.fpr, y: at.tpr, label: `operating point (threshold ${at.threshold})`, fill: 'fill-warning stroke-warning-ink' }] : []}
      summary={`ROC curve of the approvability score, area under the curve ${a.roc_auc ?? 'n/a'}.`}
    />
  );
}

function PrChart({ a }: { a: Analysis }) {
  const at = nearest(a.pr, a.thresholds.approve);
  return (
    <XYChart
      id="pr-chart"
      title={`Precision and recall (AP ${a.average_precision == null ? 'n/a' : a.average_precision.toFixed(3)})`}
      xLabel="Recall"
      yLabel="Precision"
      xDomain={[0, 1]}
      yDomain={[0, 1]}
      series={[{ name: 'Model', points: a.pr.map((p) => [p.recall, p.precision] as const), stroke: 'stroke-info-strong' }]}
      dots={at ? [{ x: at.recall, y: at.precision, label: `operating point (threshold ${at.threshold})`, fill: 'fill-warning stroke-warning-ink' }] : []}
      summary={`Precision against recall for approving, average precision ${a.average_precision ?? 'n/a'}.`}
    />
  );
}

/** Settings page slot: a summary of the saved costs and a link to the full page. */
export function CostSummary() {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/cost-matrix')), []);
  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the costs…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} />;
  const { costs, thresholds } = loaded.data;
  return (
    <div class="flex flex-col gap-2">
      <dl class="grid grid-cols-2 gap-2 md:grid-cols-5">
        {KNOBS.map((k) => (
          <div key={k.key} class="border border-line px-2 py-1">
            <dt class="text-xs text-ink-subtle">{k.label}</dt>
            <dd class="font-mono text-base font-semibold tabular-nums">{costs[k.key]}</dd>
          </div>
        ))}
      </dl>
      <p>
        These give an approve threshold of <span class="font-mono">{thresholds.approve}</span> and a reject threshold of <span class="font-mono">{thresholds.reject}</span>.
      </p>
      <p>
        <a href="/staff/costs">Open Cost of being wrong</a> to move the sliders, see the curves and save new costs.
      </p>
    </div>
  );
}
