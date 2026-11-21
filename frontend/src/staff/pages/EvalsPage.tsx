import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { HBars } from '../charts';
import { fmtTime, num, pct, Section, TD, Th, useLoad } from '../ui';

type Live = components['schemas']['LiveStats'];
type Labelled = components['schemas']['LabelledStats'];

const ms = (v: number | null | undefined): string => (v == null ? 'n/a' : `${v.toFixed(0)} ms`);

function Stat({ label, value, sub, bad, tid }: { label: string; value: string; sub?: string; bad?: boolean; tid?: string }) {
  return (
    <div class={`border px-2 py-1 ${bad ? 'border-danger bg-danger-soft' : 'border-line'}`}>
      <dt class="text-xs text-ink-subtle">{label}</dt>
      <dd class="text-lg font-semibold tabular-nums" data-testid={tid}>
        {value}
      </dd>
      {sub ? <dd class="text-xs text-ink-muted">{sub}</dd> : null}
    </div>
  );
}

/** What the system gets right and wrong: held-out labelled cases for accuracy, live decisions for behaviour. */
export function EvalsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [sum, reload] = useLoad(() => call(api.GET('/v1/evals/summary')), []);
  const [runs, reloadRuns] = useLoad(() => call(api.GET('/v1/evals/runs', { params: { query: { limit: 20 } } })), []);
  const [names] = useLoad(() => call(api.GET('/v1/evals/names')), []);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-baseline gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Evaluation
        </h1>
        <button type="button" class="h-8 rounded-sm border border-line-strong px-3 hover:bg-sunken" onClick={() => { reload(); reloadRuns(); }}>
          Refresh
        </button>
        {sum.state === 'ok' ? <span class="text-xs text-ink-subtle">Generated {fmtTime(sum.data.generated_at)}</span> : null}
      </div>
      {sum.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Reading the evaluation summary…" /> : null}
      {sum.state === 'fail' ? <FailureState failure={sum.failure} density="staff" onRetry={reload} /> : null}
      {sum.state === 'ok' ? (
        <>
          <dl class="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Silent guesses, all decisions" value={String(sum.data.silent_guesses_total)} sub="Must read 0" bad={sum.data.silent_guesses_total !== 0} tid="silent-total" />
            <Stat label="Live decisions" value={String(sum.data.live_overall.decisions)} sub={`${pct(sum.data.live_overall.auto_rate)} automatic`} />
            <Stat label="Latency p50 / p95" value={`${ms(sum.data.live_overall.latency_ms_p50)} / ${ms(sum.data.live_overall.latency_ms_p95)}`} />
            <Stat label="Cost per decision (live)" value={num(sum.data.live_overall.expected_cost_per_decision)} sub="units, expected" />
          </dl>
          {sum.data.notes.length > 0 ? <p class="text-xs text-ink-subtle">{sum.data.notes.join(' ')}</p> : null}
          {sum.data.labelled ? <LabelledBlock s={sum.data.labelled} /> : <ScreenState kind="empty" density="staff" title="No labelled evaluation" body="The held-out labelled cases have not been scored." />}
          <Section id="live" title="Live decisions by rule version">
            <LiveTable rows={[sum.data.live_overall, ...sum.data.live_by_rule_version]} />
          </Section>
          {sum.data.labelled_by_rule_version.length > 0 ? (
            <Section id="lab-ver" title="Labelled cases by rule version">
              <LabelledTable rows={sum.data.labelled_by_rule_version} />
            </Section>
          ) : null}
          <Section id="names" title="Dedupe: messy name pairs">
            <div class="flex flex-col gap-2">
              <dl class="grid grid-cols-2 gap-2 md:grid-cols-4">
                <Stat label="Labelled pairs" value={String(sum.data.names.fixtures)} sub={`${sum.data.names.kinds} kinds of mess`} />
                <Stat label="Duplicates caught (recall)" value={pct(sum.data.names.duplicates_caught_recall)} />
                <Stat label="Wrong links" value={String(sum.data.names.wrong_links)} sub="Must read 0" bad={sum.data.names.wrong_links !== 0} tid="wrong-links" />
                <Stat label="As expected" value={names.state === 'ok' ? pct((names.data as { as_expected?: number }).as_expected) : 'n/a'} />
              </dl>
              <table class="w-full max-w-xl border-collapse text-sm">
                <thead>
                  <tr>
                    <Th>Band</Th>
                    <Th>Predicted</Th>
                    <Th>Precision</Th>
                    <Th>Recall</Th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(sum.data.names.bands).map(([band, v]) => (
                    <tr key={band}>
                      <td class={TD}>{band}</td>
                      <td class={`${TD} text-end font-mono tabular-nums`}>{String(v.predicted ?? '')}</td>
                      <td class={`${TD} text-end font-mono tabular-nums`}>{pct(v.precision as number)}</td>
                      <td class={`${TD} text-end font-mono tabular-nums`}>{pct(v.recall as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      ) : null}
      <Section id="runs" title="Stored evaluation runs">
        {runs.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading runs…" /> : null}
        {runs.state === 'fail' ? <FailureState failure={runs.failure} density="staff" heading="h2" onRetry={reloadRuns} /> : null}
        {runs.state === 'ok' && runs.data.items.length === 0 ? <ScreenState kind="empty" density="staff" title="No stored runs" body="Runs are stored by an admin from the cost page API; nothing has been stored yet. The numbers above are computed live." /> : null}
        {runs.state === 'ok' && runs.data.items.length > 0 ? (
          <table class="w-full border-collapse text-sm">
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Kind</Th>
                <Th>Model</Th>
                <Th>Metrics</Th>
              </tr>
            </thead>
            <tbody>
              {runs.data.items.map((r) => (
                <tr key={r.id}>
                  <td class={TD}>{fmtTime(r.created_at)}</td>
                  <td class={TD}>{r.kind}</td>
                  <td class={`${TD} font-mono text-xs`}>{r.model_version ?? 'n/a'}</td>
                  <td class={`${TD} font-mono text-xs`}>{JSON.stringify(r.metrics).slice(0, 200)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Section>
    </section>
  );
}

function LabelledBlock({ s }: { s: Labelled }) {
  return (
    <Section id="labelled" title={`Held-out labelled cases (${s.cases}, rule version ${s.rule_version_no ?? 'n/a'})`}>
      <dl class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Silent guesses" value={String(s.silent_guesses)} sub="Must read 0" bad={s.silent_guesses !== 0} tid="silent-labelled" />
        <Stat label="Abstention" value={pct(s.abstention_rate)} sub="sent to a person or proof" />
        <Stat label="False approvals" value={`${s.false_approvals}`} sub={`${(s.false_approve_rate * 100).toFixed(2)}% of cases`} />
        <Stat label="False rejections" value={`${s.false_rejections}`} sub={`${(s.false_reject_rate * 100).toFixed(2)}% of cases`} />
        <Stat label="Accuracy when automatic" value={pct(s.accuracy_of_automatic)} />
        <Stat label="Unnecessary handoffs" value={String(s.unnecessary_handoffs)} />
        <Stat label="Cost per case" value={num(s.cost_per_case)} sub={`all-human ${num(s.all_human_cost_per_case)}`} />
        <Stat label="ECE / AUC" value={`${num(s.ece, 3)} / ${num(s.roc_auc, 3)}`} />
      </dl>
    </Section>
  );
}

function LiveTable({ rows }: { rows: readonly Live[] }) {
  return (
    <div class="flex flex-col gap-3">
      <div class="overflow-auto">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr>
              <Th>Rule version</Th>
              <Th>Decisions</Th>
              <Th>Auto rate</Th>
              <Th>Abstention</Th>
              <Th>Silent guesses</Th>
              <Th>Latency p50</Th>
              <Th>Latency p95</Th>
              <Th>Cost per decision</Th>
              <Th>Officer overrides</Th>
              <Th>Engine fallbacks</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.rule_version_id ?? 'all'} class={i === 0 ? 'bg-sunken font-semibold' : ''}>
                <td class={TD}>{r.rule_version_no ? `Version ${r.rule_version_no}` : 'All'}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{r.decisions}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{pct(r.auto_rate)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{pct(r.abstention_rate)}</td>
                <td class={`${TD} text-end font-mono tabular-nums ${r.silent_guesses ? 'text-danger' : ''}`}>{r.silent_guesses}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{ms(r.latency_ms_p50)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{ms(r.latency_ms_p95)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{num(r.expected_cost_per_decision)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>
                  {r.officer_overrides} of {r.officer_reviews}
                </td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{r.engine_fallbacks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows[0] && rows[0].decisions > 0 ? (
        <div class="grid gap-4 md:grid-cols-2">
          <div>
            <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Outcomes (all versions)</h3>
            <HBars rows={Object.entries(rows[0].outcomes).map(([label, value]) => ({ label: label.replace(/_/g, ' '), value }))} />
          </div>
          <div>
            <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Routes (all versions)</h3>
            <HBars rows={Object.entries(rows[0].routes).map(([label, value]) => ({ label: label.replace(/_/g, ' '), value, cls: 'fill-primary' }))} />
          </div>
        </div>
      ) : (
        <p class="text-ink-muted">No live decisions yet.</p>
      )}
    </div>
  );
}

function LabelledTable({ rows }: { rows: readonly Labelled[] }) {
  return (
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr>
          <Th>Rule version</Th>
          <Th>Cases</Th>
          <Th>False approvals</Th>
          <Th>False rejections</Th>
          <Th>Abstention</Th>
          <Th>Silent guesses</Th>
          <Th>Cost per case</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.rule_version_id ?? r.run_id}>
            <td class={TD}>Version {r.rule_version_no ?? 'n/a'}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{r.cases}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{r.false_approvals}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{r.false_rejections}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{pct(r.abstention_rate)}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{r.silent_guesses}</td>
            <td class={`${TD} text-end font-mono tabular-nums`}>{num(r.cost_per_case)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
