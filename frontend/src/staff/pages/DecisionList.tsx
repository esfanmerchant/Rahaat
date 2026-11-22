import { useState } from 'preact/hooks';
import { Rise } from '../Rise';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN_PRIMARY, flashFail, FlashLine, LoadMore, usePaged } from '../kit';
import { prefersReducedMotion } from '../theme';
import { Badge, ConfBar, fmtTime, humanize, INPUT, Mono, num, TD, Th } from '../ui';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type Summary = components['schemas']['DecisionSummary'];
const ROUTES = ['', 'auto', 'ask_more', 'human'] as const;
const OUTCOMES = ['', 'approved', 'rejected', 'needs_proof', 'needs_human'] as const;
type RouteF = (typeof ROUTES)[number];
type OutcomeF = (typeof OUTCOMES)[number];

/** The decision list: filtered, newest first, no personal data. Open one to see the citizen's reason beside the trace. */
export function DecisionIndex() {
  const { route: go } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [route, setRoute] = useState<RouteF>('');
  const [outcome, setOutcome] = useState<OutcomeF>('');
  const [version, setVersion] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [id, setId] = useState('');
  const [touched, setTouched] = useState(false);
  const valid = UUID.test(id.trim());
  const vno = Number(version);
  const list = usePaged<Summary>(
    (cursor) =>
      call(
        api.GET('/v1/decisions', {
          params: {
            query: {
              limit: 25,
              ...(route ? { route } : {}),
              ...(outcome ? { outcome } : {}),
              ...(version && Number.isInteger(vno) && vno > 0 ? { rule_version_no: vno } : {}),
              ...(from ? { decided_from: from } : {}),
              ...(to ? { decided_to: to } : {}),
              ...(cursor ? { cursor: String(cursor) } : {}),
            },
          },
        }),
      ),
    [route, outcome, version, from, to],
  );
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <h1 id="page-title" ref={headingRef} tabIndex={-1}>
        <Rise text="Decisions" />
      </h1>
      <form class="flex flex-wrap items-end gap-2" onSubmit={(e) => e.preventDefault()}>
        <label class="flex flex-col gap-1">
          Route
          <select class={INPUT} value={route} onChange={(e) => setRoute(e.currentTarget.value as RouteF)}>
            {ROUTES.map((r) => (
              <option key={r} value={r}>
                {r ? humanize(r) : 'any'}
              </option>
            ))}
          </select>
        </label>
        <label class="flex flex-col gap-1">
          Outcome
          <select class={INPUT} value={outcome} onChange={(e) => setOutcome(e.currentTarget.value as OutcomeF)}>
            {OUTCOMES.map((r) => (
              <option key={r} value={r}>
                {r ? humanize(r) : 'any'}
              </option>
            ))}
          </select>
        </label>
        <label class="flex flex-col gap-1">
          Rule version
          <input class={`${INPUT} w-20`} inputMode="numeric" value={version} onInput={(e) => setVersion(e.currentTarget.value)} />
        </label>
        <label class="flex flex-col gap-1">
          From
          <input class={INPUT} type="date" value={from} onInput={(e) => setFrom(e.currentTarget.value)} />
        </label>
        <label class="flex flex-col gap-1">
          To
          <input class={INPUT} type="date" value={to} onInput={(e) => setTo(e.currentTarget.value)} />
        </label>
      </form>
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading decisions…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? (
        <ScreenState kind="empty" density="staff" title="No decisions match" body="No decision has been recorded with these filters. A decision is recorded when a citizen submits an application." />
      ) : null}
      {list.status === 'ok' && list.items.length > 0 ? (
        <div class="overflow-auto">
          <table class="w-full border-collapse text-sm">
            <thead>
              <tr>
                <Th>Decided</Th>
                <Th>Outcome</Th>
                <Th>Route</Th>
                <Th>p_ok</Th>
                <Th>Expected cost</Th>
                <Th>Main reason</Th>
                <Th>Rule version</Th>
                <Th>Guards</Th>
                <Th>Open</Th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((d) => (
                <tr key={d.id}>
                  <td class={TD}>{fmtTime(d.decided_at)}</td>
                  <td class={TD}>
                    <Badge>{d.outcome}</Badge>
                  </td>
                  <td class={TD}>
                    <Badge tone="info">{d.route}</Badge>
                  </td>
                  <td class={TD}>
                    <ConfBar value={d.p_ok} />
                  </td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{num(d.expected_cost)}</td>
                  <td class={`${TD} text-xs`}>{d.main_reason ? humanize(d.main_reason) : 'n/a'}</td>
                  <td class={TD}>{d.rule_version_no ?? 'n/a'}</td>
                  <td class={`${TD} text-xs`}>{d.guards?.length ? d.guards.join(', ') : 'none'}</td>
                  <td class={TD}>
                    <a href={`/staff/decisions/${d.id}`}>
                      <Mono>{d.id.slice(0, 8)}</Mono>
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
      <form
        class="flex flex-wrap items-end gap-2 border-t border-line pt-2"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          if (valid) go(`/staff/decisions/${id.trim()}`);
        }}
      >
        <label class="flex flex-col gap-1">
          Open by decision id
          <input class={`${INPUT} w-96 max-w-full font-mono`} value={id} aria-invalid={touched && !valid} autoComplete="off" spellcheck={false} onInput={(e) => setId(e.currentTarget.value)} />
        </label>
        <Button size="sm" type="submit">
          Open decision
        </Button>
        {touched && !valid ? (
          <span role="alert" class="text-danger">
            That is not a decision id.
          </span>
        ) : null}
      </form>
    </section>
  );
}

export interface ReplayFacts {
  inputHash?: string;
  engine?: string;
  model?: string;
  ruleVersion?: number;
  outcome?: string;
}

const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

/**
 * Recompute from the stored snapshot and pinned versions, and show the proof as three steps: the stored inputs,
 * the engine, then the same outcome with both hashes. The call is real; the pacing only lets the eye follow it.
 */
export function ReplayBox({ id, facts = {} }: { id: string; facts?: ReplayFacts }) {
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [res, setRes] = useState<Result<components['schemas']['ReplayResult']> | null>(null);
  const run = async () => {
    setBusy(true);
    setRes(null);
    setStage(1);
    const fast = prefersReducedMotion();
    const call$ = call(api.POST('/v1/decisions/{decision_id}/replay', { params: { path: { decision_id: id } } }));
    await wait(fast ? 0 : 700);
    setStage(2);
    const [r] = await Promise.all([call$, wait(fast ? 0 : 900)]);
    setRes(r);
    setStage(3);
    setBusy(false);
  };
  const ok = res?.ok ? res.data : null;
  const step = (n: number, title: string, body: preact.ComponentChildren, state: 'idle' | 'live' | 'done' | 'bad') => (
    <li class={`st-panel flex-1 p-3 ${state === 'idle' ? 'opacity-40' : 'st-sweep'} ${state === 'done' ? 'st-lit' : ''}`} aria-current={state === 'live' ? 'step' : undefined}>
      <p class="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        <span class="inline-flex h-5 w-5 items-center justify-center rounded-full border border-line-strong font-mono">{n}</span>
        {title}
        {state === 'live' ? <span class="st-live" aria-hidden="true" /> : null}
      </p>
      {body}
    </li>
  );
  return (
    <div class="flex flex-col gap-3">
      <p class="text-ink-muted">Replay recomputes the decision from its stored input snapshot and the pinned rule, model and engine versions, then compares the result hash. Nothing is stored.</p>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class={BTN_PRIMARY} disabled={busy} onClick={() => void run()}>
          {busy ? 'Replaying…' : 'Replay this decision'}
        </button>
        <a href={`/staff/audit?object_id=${encodeURIComponent(id)}`}>Audit rows</a>
        <a href="/staff/audit">Verify the audit chain</a>
      </div>
      {res && !res.ok ? <FlashLine flash={flashFail(res.failure)} /> : null}
      {stage > 0 ? (
        <ol class="flex flex-col gap-2 lg:flex-row" aria-label="Replay steps" aria-live="polite">
          {step(1, 'Stored inputs', (
            <div class="text-xs">
              <p>The snapshot saved when the decision was made.</p>
              {facts.inputHash ? <p class="mt-1 break-all font-mono text-ink-muted">input {facts.inputHash.slice(0, 24)}…</p> : null}
            </div>
          ), stage > 1 ? 'done' : 'live')}
          {step(2, 'Engine', (
            <div class="text-xs">
              <p>Pinned versions run again, with nothing newer.</p>
              <p class="mt-1 font-mono text-ink-muted">{[facts.ruleVersion ? `rules v${facts.ruleVersion}` : '', facts.model ?? '', facts.engine ?? ''].filter(Boolean).join(' · ')}</p>
            </div>
          ), stage > 2 ? 'done' : stage === 2 ? 'live' : 'idle')}
          {step(3, 'Outcome', ok ? (
            <div role="status" data-testid="replay-result" class="text-xs">
              <p class={`flex items-center gap-2 text-sm font-bold ${ok.match ? 'text-primary' : 'text-danger'}`}>
                <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" class="st-seal">
                  <circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" stroke-width="1.6" />
                  {ok.match ? <path d="M5 9.4 7.8 12 13 6.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /> : <path d="M6 6l6 6M12 6l-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" />}
                </svg>
                {ok.match ? 'Replay matches: the same input gives the same decision, byte for byte.' : 'Replay does not match. The decision differs from the stored one.'}
              </p>
              {facts.outcome ? <p class="mt-1">Outcome <Badge>{facts.outcome}</Badge></p> : null}
              <p class="mt-1 break-all font-mono">stored {ok.stored_result_hash ?? 'none'}</p>
              <p class="break-all font-mono">replayed {ok.replayed_result_hash}</p>
              {ok.differences?.length ? (
                <ul class="ps-4">
                  {ok.differences.map((d) => (
                    <li key={d} class="list-disc">{d}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : <p class="text-xs text-ink-subtle">Waiting for the engine…</p>, ok ? (ok.match ? 'done' : 'bad') : stage === 3 ? 'bad' : 'idle')}
        </ol>
      ) : null}
    </div>
  );
}
