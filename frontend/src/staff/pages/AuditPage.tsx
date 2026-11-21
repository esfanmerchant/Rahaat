import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { SectionTabs } from '../SectionTabs';
import { prefersReducedMotion } from '../theme';
import { Badge, fmtTime, INPUT, Mono, TD, Th, useLoad, type AuditEntry, type ChainOut } from '../ui';
import { CountUp } from '../viz';
import { Card, Info } from './pg';

const PAGE = 25;
/** How many of the newest blocks are drawn; the verification itself always covers the whole chain. */
const SHOWN = 12;

interface Filters {
  action: string;
  result: '' | 'ok' | 'denied' | 'failed';
  actor_id: string;
  object_id: string;
}

type BlockState = 'idle' | 'scan' | 'ok' | 'bad' | 'unchecked';

/** Auditor and admin view of the append-only trail, newest first, with chain verification. */
export function AuditPage() {
  const { query } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const initial: Filters = {
    action: query['action'] ?? '',
    result: (['ok', 'denied', 'failed'].includes(query['result'] ?? '') ? query['result'] : '') as Filters['result'],
    actor_id: query['actor_id'] ?? '',
    object_id: query['object_id'] ?? '',
  };
  const [draft, setDraft] = useState<Filters>(initial);
  const [applied, setApplied] = useState<Filters>(initial);
  // Cursor stack: trail[n] is the cursor that produced page n (undefined for the first page).
  const [trail, setTrail] = useState<Array<number | undefined>>([undefined]);
  const [open, setOpen] = useState<AuditEntry | null>(null);
  const cursor = trail[trail.length - 1];

  const [loaded, reload] = useLoad(
    () =>
      call(
        api.GET('/v1/audit', {
          params: {
            query: {
              limit: PAGE,
              ...(cursor !== undefined ? { cursor } : {}),
              ...(applied.action ? { action: applied.action } : {}),
              ...(applied.result ? { result: applied.result } : {}),
              ...(applied.actor_id ? { actor_id: applied.actor_id } : {}),
              ...(applied.object_id ? { object_id: applied.object_id } : {}),
            },
          },
        }),
      ),
    [cursor, applied],
  );

  const items = loaded.state === 'ok' ? loaded.data.items : [];
  const next = loaded.state === 'ok' ? loaded.data.next_cursor : null;
  // Oldest first, so the chain reads left to right.
  const chain = [...items].sort((a, b) => a.seq - b.seq);
  const verify = useVerify(chain);

  const apply = (event: Event) => {
    event.preventDefault();
    setTrail([undefined]);
    setOpen(null);
    setApplied({ ...draft, action: draft.action.trim(), actor_id: draft.actor_id.trim(), object_id: draft.object_id.trim() });
  };
  const clear = () => {
    const empty: Filters = { action: '', result: '', actor_id: '', object_id: '' };
    setDraft(empty);
    setApplied(empty);
    setTrail([undefined]);
    setOpen(null);
  };

  const state =
    loaded.state === 'loading' ? (
      <ScreenState kind="loading" density="staff" body="Loading the trail…" />
    ) : loaded.state === 'fail' ? (
      <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} />
    ) : null;

  const brokenSeq = verify.data && !verify.data.ok ? (verify.data.first_broken_seq ?? null) : null;

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="pg-head pg-rise">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} style={{ fontSize: '1.5rem' }}>
          Audit chain
        </h1>
        <span class="st-chip" title="Append-only; nothing here can be edited">
          append-only
        </span>
        {verify.data ? (
          <span class={`st-chip ${verify.data.ok ? 'ok' : 'bad'}`}>{verify.data.ok ? 'verified' : `broken at ${brokenSeq ?? '?'}`}</span>
        ) : null}
        <span class="ms-auto">
          <Info label="About the chain">Each row stores the hash of the row before it. Changing any row breaks every link after it. Verify recomputes every hash from the start and is itself written to the trail.</Info>
        </span>
      </div>

      <SectionTabs
        label="Audit sections"
        sections={[
          { id: 'chain', label: 'Chain' },
          { id: 'events', label: 'Events', badge: items.length || undefined },
          { id: 'integrity', label: 'Integrity', badge: brokenSeq !== null ? '!' : undefined },
        ]}
      >
        {(tab) => {
          if (tab === 'chain') {
            return (
              <div class="flex flex-col gap-3">
                <Card title="Chain" i={0} aside={<VerifyButton verify={verify} />}>
                  {state}
                  {loaded.state === 'ok' && items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No audit rows" body="Nothing matches. Clear the filters." /> : null}
                  {chain.length > 0 ? (
                    <ChainStrip rows={chain.slice(-SHOWN)} states={verify.states.slice(-SHOWN)} hidden={Math.max(0, chain.length - SHOWN)} onPick={setOpen} openSeq={open?.seq} />
                  ) : null}
                  <div aria-live="polite" class="flex min-h-16 flex-wrap items-center gap-4">
                    <VerifySeal verify={verify} />
                    {verify.data ? (
                      <dl class="flex flex-wrap gap-3">
                        <div class="rounded-xl border border-line px-3 py-1.5">
                          <dt class="pg-cap">Rows</dt>
                          <dd class="pg-big rh-num" style={{ fontSize: '1.5rem' }}>{verify.data.checked}</dd>
                        </div>
                        <div class="rounded-xl border border-line px-3 py-1.5">
                          <dt class="pg-cap">Head</dt>
                          <dd class="pg-big rh-num" style={{ fontSize: '1.5rem' }}>#{verify.data.head_seq}</dd>
                        </div>
                      </dl>
                    ) : null}
                  </div>
                </Card>
                {open ? <RowDetail row={open} onClose={() => setOpen(null)} /> : null}
              </div>
            );
          }
          if (tab === 'events') {
            return (
              <div class="flex flex-col gap-3">
                <Card i={0}>
                  <form class="flex flex-wrap items-end gap-2" onSubmit={apply} aria-label="Audit filters">
                    <label class="flex flex-col gap-0.5 text-xs">
                      Action
                      <input class={`${INPUT} w-44 font-mono`} value={draft.action} placeholder="case." autoComplete="off" title="Exact, or a prefix ending in a dot" onInput={(e) => setDraft({ ...draft, action: e.currentTarget.value })} />
                    </label>
                    <label class="flex flex-col gap-0.5 text-xs">
                      Result
                      <select class={INPUT} value={draft.result} onChange={(e) => setDraft({ ...draft, result: e.currentTarget.value as Filters['result'] })}>
                        <option value="">Any</option>
                        <option value="ok">ok</option>
                        <option value="denied">denied</option>
                        <option value="failed">failed</option>
                      </select>
                    </label>
                    <label class="flex flex-col gap-0.5 text-xs">
                      Actor id
                      <input class={`${INPUT} w-56 font-mono`} value={draft.actor_id} autoComplete="off" onInput={(e) => setDraft({ ...draft, actor_id: e.currentTarget.value })} />
                    </label>
                    <label class="flex flex-col gap-0.5 text-xs">
                      Object id
                      <input class={`${INPUT} w-56 font-mono`} value={draft.object_id} autoComplete="off" onInput={(e) => setDraft({ ...draft, object_id: e.currentTarget.value })} />
                    </label>
                    <Button size="sm" type="submit">
                      Apply
                    </Button>
                    <Button size="sm" variant="neutral" onClick={clear}>
                      Clear
                    </Button>
                    <span class="ms-auto flex items-center gap-2">
                      <Button size="sm" variant="neutral" disabled={trail.length <= 1} onClick={() => { setTrail(trail.slice(0, -1)); setOpen(null); }}>
                        Newer
                      </Button>
                      <span class="st-chip font-mono">p{trail.length}</span>
                      <Button
                        size="sm"
                        variant="neutral"
                        disabled={!next}
                        onClick={() => {
                          if (next) {
                            setTrail([...trail, Number(next)]);
                            setOpen(null);
                          }
                        }}
                      >
                        Older
                      </Button>
                    </span>
                  </form>
                </Card>
                {state}
                {loaded.state === 'ok' && items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No audit rows" body="Nothing matches. Clear the filters." /> : null}
                {items.length > 0 ? (
                  <div class="grid items-start gap-3" style={{ gridTemplateColumns: open ? 'minmax(0,1fr) 24rem' : 'minmax(0,1fr)' }}>
                    <div class="pg-card pg-rise pg-scroll" style={{ '--i': 1, padding: 0 }}>
                      <table class="st-table w-full border-collapse text-sm">
                        <caption class="sr-only">Audit trail, newest first. Select a row to see its hashes and details.</caption>
                        <thead>
                          <tr>
                            <Th>Seq</Th>
                            <Th>Time (UTC)</Th>
                            <Th>Action</Th>
                            <Th>Result</Th>
                            <Th>Actor</Th>
                            <Th>Object</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((r, i) => (
                            <tr key={r.seq} aria-selected={open?.seq === r.seq} class={`st-row-in ${open?.seq === r.seq ? 'st-cursor' : ''}`} style={{ '--i': i }}>
                              <td class={`${TD} font-mono tabular-nums`}>
                                <button type="button" class="font-mono underline" onClick={() => setOpen(r)} aria-label={`Show row ${r.seq}`}>
                                  {r.seq}
                                </button>
                              </td>
                              <td class={`${TD} font-mono text-xs`}>{fmtTime(r.ts)}</td>
                              <td class={`${TD} font-mono text-xs`}>{r.action}</td>
                              <td class={TD}>
                                <Badge tone={r.result === 'ok' ? 'good' : r.result === 'denied' ? 'warn' : 'bad'}>{r.result}</Badge>
                              </td>
                              <td class={TD}>
                                <span class="text-xs">{r.actor_role ?? r.actor_type}</span> {r.actor_id ? <Mono>{r.actor_id.slice(0, 8)}</Mono> : null}
                              </td>
                              <td class={TD}>{r.object_type ? <span class="text-xs">{r.object_type} {r.object_id ? <Mono>{r.object_id.slice(0, 8)}</Mono> : null}</span> : null}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {open ? <RowDetail row={open} onClose={() => setOpen(null)} /> : null}
                  </div>
                ) : null}
              </div>
            );
          }
          return <Integrity verify={verify} />;
        }}
      </SectionTabs>
    </section>
  );
}

function RowDetail({ row, onClose }: { row: AuditEntry; onClose: () => void }) {
  const facts: Array<[string, string | null | undefined]> = [
    ['Sequence', String(row.seq)],
    ['Time', row.ts],
    ['Action', row.action],
    ['Result', row.result],
    ['Reason', row.reason],
    ['Actor type', row.actor_type],
    ['Actor role', row.actor_role],
    ['Actor id', row.actor_id],
    ['Acting for person', row.acting_for_person_id],
    ['Object', row.object_type ? `${row.object_type} ${row.object_id ?? ''}` : null],
    ['Input hash', row.input_hash],
    ['Model version', row.model_version],
    ['Rule version', row.rule_version_id],
    ['Request id', row.request_id],
    ['Previous hash', row.prev_hash],
    ['Row hash', row.hash],
  ];
  return (
    <aside aria-label={`Audit row ${row.seq}`} class="pg-card pg-rise" style={{ padding: 0 }}>
      <div class="flex items-center justify-between border-b border-line px-3 py-1.5">
        <h2 class="pg-cap">Row {row.seq}</h2>
        <button type="button" class="text-xs underline" onClick={onClose}>
          Close
        </button>
      </div>
      <dl class="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 p-3 text-xs">
        {facts
          .filter(([, v]) => v !== null && v !== undefined && v !== '')
          .map(([k, v]) => (
            <>
              <dt key={`${k}-k`} class="font-semibold text-ink-muted">
                {k}
              </dt>
              <dd key={`${k}-v`} class="break-all font-mono">
                {v}
              </dd>
            </>
          ))}
      </dl>
      <div class="border-t border-line p-3">
        <h3 class="pg-cap mb-1">Details</h3>
        <pre class="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-sunken p-2 font-mono text-xs">{JSON.stringify(row.details, null, 2)}</pre>
        <p class="mt-2 flex gap-3 text-xs">
          {(row.object_type === 'agent_run' || (row.object_type === 'agent_step' && typeof (row.details as Record<string, unknown> | null)?.['run_id'] === 'string')) && row.object_id ? (
            <a href={`/staff/agent-runs/${row.object_type === 'agent_run' ? row.object_id : String((row.details as Record<string, unknown>)['run_id'])}`}>Assistant run</a>
          ) : null}
          {row.object_type === 'decision' && row.object_id ? <a href={`/staff/decisions/${row.object_id}`}>Decision</a> : null}
        </p>
      </div>
    </aside>
  );
}

/** The newest rows as linked blocks: each block holds its own hash and the previous one, so a change breaks the link. */
function ChainStrip({ rows, states, hidden, onPick, openSeq }: { rows: AuditEntry[]; states: BlockState[]; hidden: number; onPick: (r: AuditEntry) => void; openSeq: number | undefined }) {
  return (
    <ol class="pg-chain" aria-label="Audit rows as a hash chain, oldest on the left">
      {hidden > 0 ? (
        <li class="flex items-center">
          <span class="st-chip font-mono" title="Older rows on this page are not drawn">+{hidden}</span>
          <span class="pg-link" aria-hidden="true" />
        </li>
      ) : null}
      {rows.map((r, i) => {
        const st = states[i] ?? 'idle';
        return (
          <li key={r.seq} class="flex items-stretch">
            {i > 0 ? <span class={`pg-link ${st === 'ok' ? 'ok' : st === 'bad' ? 'bad' : ''}`} style={{ '--i': i }} aria-hidden="true" /> : null}
            <button
              type="button"
              onClick={() => onPick(r)}
              class={`pg-block ${st === 'ok' ? 'ok' : st === 'bad' ? 'bad' : st === 'scan' ? 'scan' : ''}`}
              style={{ '--i': i, outline: openSeq === r.seq ? '2px solid var(--st-noor)' : undefined }}
              aria-label={`Row ${r.seq}, ${r.action}, ${st === 'ok' ? 'verified' : st === 'bad' ? 'broken' : 'not yet checked'}`}
            >
              <span class="rh-num block font-mono text-sm font-bold">#{r.seq}</span>
              <span class="block truncate text-[0.65rem] text-ink-muted">{r.action}</span>
              <span class="block truncate font-mono text-[0.65rem] text-ink-subtle" title={r.hash ?? ''}>
                {(r.hash ?? '').slice(0, 10)}
              </span>
              <span class="block truncate font-mono text-[0.6rem] text-ink-subtle" title={r.prev_hash ?? ''}>
                &larr; {(r.prev_hash ?? '').slice(0, 6)}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

interface Verify {
  busy: boolean;
  outcome: Result<ChainOut> | null;
  data: ChainOut | null;
  states: BlockState[];
  olderBreak: boolean;
  run: () => Promise<void>;
}

/** Verify the chain: a light sweeps the drawn blocks while the real request runs; the answer decides each block's state. */
function useVerify(chain: AuditEntry[]): Verify {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Result<ChainOut> | null>(null);
  const [scan, setScan] = useState<number | null>(null);
  const run = async () => {
    setBusy(true);
    setOutcome(null);
    const fast = prefersReducedMotion();
    const req = call(api.GET('/v1/audit/verify'));
    if (!fast) {
      for (let i = 0; i < chain.length; i++) {
        setScan(i);
        await new Promise((r) => window.setTimeout(r, Math.max(30, Math.min(110, 1800 / chain.length))));
      }
    }
    const res = await req;
    setScan(null);
    setOutcome(res);
    setBusy(false);
  };
  const data = outcome && outcome.ok ? outcome.data : null;
  const broken = data && !data.ok ? (data.first_broken_seq ?? null) : null;
  const states: BlockState[] = chain.map((r, i) => {
    if (scan !== null) return i === scan ? 'scan' : 'idle';
    if (!data) return 'idle';
    if (data.ok) return 'ok';
    if (broken === null) return 'unchecked';
    return r.seq < broken ? 'ok' : r.seq === broken ? 'bad' : 'unchecked';
  });
  const olderBreak = !!data && !data.ok && broken !== null && chain.length > 0 && broken < (chain[0]?.seq ?? 0);
  return { busy, outcome, data, states, olderBreak, run };
}

function VerifyButton({ verify }: { verify: Verify }) {
  return (
    <Button size="sm" busy={verify.busy} onClick={() => void verify.run()}>
      Verify chain
    </Button>
  );
}

function VerifySeal({ verify }: { verify: Verify }) {
  const { outcome, data } = verify;
  if (outcome === null) return null;
  if (!outcome.ok) return <FailureState failure={outcome.failure} density="staff" heading="h2" onRetry={() => void verify.run()} />;
  if (data && data.ok) {
    return (
      <div class="pg-seal">
        <svg width="38" height="38" viewBox="0 0 34 34" aria-hidden="true">
          <circle cx="17" cy="17" r="15" fill="none" stroke="currentColor" stroke-width="2" />
          <circle cx="17" cy="17" r="11" fill="none" stroke="currentColor" stroke-width="1" opacity="0.5" />
          <path d="M10.5 17.5 15 22l8.5-10" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="rh-draw" pathLength={100} />
        </svg>
        <span class="pg-big" style={{ fontSize: '1.5rem' }}>
          <CountUp value={data.checked} ms={700} /> of {data.checked} verified
        </span>
        <span class="st-chip font-mono" title={`head hash ${data.head_hash}`}>
          head #{data.head_seq}
        </span>
      </div>
    );
  }
  return (
    <div role="alert" class="pg-seal bad">
      <span class="pg-big" style={{ fontSize: '1.4rem' }}>Broken at {data?.first_broken_seq ?? '?'}</span>
      <span class="st-chip bad">{data?.checked ?? 0} rows ok before</span>
      {verify.olderBreak ? <span class="st-chip warn">older than the rows shown</span> : null}
      {data?.problem ? <span class="st-chip font-mono">{data.problem}</span> : null}
    </div>
  );
}

/** What a break looks like. The example row is illustrative; the result below it is the real last verification. */
function Integrity({ verify }: { verify: Verify }) {
  const { data } = verify;
  const demo = [
    { seq: 41, state: 'ok' as const, h: 'a91f3c07', p: '5d20be' },
    { seq: 42, state: 'ok' as const, h: '5d20be19', p: 'a91f3c' },
    { seq: 43, state: 'bad' as const, h: '0c77e4d2', p: '5d20be' },
    { seq: 44, state: 'unchecked' as const, h: 'e2b6190a', p: '9f31aa' },
    { seq: 45, state: 'unchecked' as const, h: '71c8d0f4', p: 'e2b619' },
  ];
  return (
    <div class="flex flex-col gap-3">
      <Card title="Break" i={0} lit aside={<><span class="st-chip warn">example</span><Info label="About a break">If a row is edited, its hash no longer matches what the next row remembers. Verify reports the first sequence that fails; later rows cannot be trusted either.</Info></>}>
        <ol class="pg-chain" aria-label="Example of a broken chain, illustration only">
          {demo.map((r, i) => (
            <li key={r.seq} class="flex items-stretch">
              {i > 0 ? <span class={`pg-link ${r.state === 'bad' ? 'bad' : r.state === 'ok' ? 'ok' : ''}`} style={{ '--i': i }} aria-hidden="true" /> : null}
              <div class={`pg-block ${r.state === 'ok' ? 'ok' : r.state === 'bad' ? 'bad' : ''}`} style={{ '--i': i }}>
                <span class="rh-num block font-mono text-sm font-bold">#{r.seq}</span>
                <span class="block font-mono text-[0.65rem] text-ink-subtle">{r.h}</span>
                <span class="block font-mono text-[0.6rem] text-ink-subtle">&larr; {r.p}</span>
              </div>
            </li>
          ))}
        </ol>
        <div class="pg-chips">
          <span class="st-chip ok">hash matches</span>
          <span class="st-chip bad">hash differs</span>
          <span class="st-chip unk">not trusted</span>
        </div>
      </Card>
      <Card title="Last check" i={1} lit={data !== null && !data.ok}>
        {data === null ? (
          <div class="flex flex-col items-start gap-3">
            <p class="text-ink-muted">Not run yet.</p>
            <VerifyButton verify={verify} />
          </div>
        ) : (
          <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
            <p class={`pg-big ${data.ok ? '' : 'text-danger'}`} style={data.ok ? { color: 'var(--st-ok)' } : undefined}>
              {data.ok ? 'Intact' : 'Broken'}
            </p>
            <dl class="pg-kv" style={{ flex: '1 1 18rem' }}>
              <dt>Checked</dt>
              <dd class="font-mono">{data.checked}</dd>
              <dt>Head</dt>
              <dd class="font-mono">#{data.head_seq}</dd>
              {data.ok ? null : (
                <>
                  <dt>First bad</dt>
                  <dd class="font-mono text-danger">#{data.first_broken_seq ?? '?'}</dd>
                </>
              )}
              <dt>Head hash</dt>
              <dd class="pg-hash">{data.head_hash}</dd>
            </dl>
            <VerifyButton verify={verify} />
          </div>
        )}
      </Card>
    </div>
  );
}
