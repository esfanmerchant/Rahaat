import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Badge, fmtTime, INPUT, Mono, TD, Th, useLoad, type AuditEntry, type ChainOut } from '../ui';

const PAGE = 25;

interface Filters {
  action: string;
  result: '' | 'ok' | 'denied' | 'failed';
  actor_id: string;
  object_id: string;
}

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

  const items = loaded.state === 'ok' ? loaded.data.items : [];
  const next = loaded.state === 'ok' ? loaded.data.next_cursor : null;

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Audit trail
        </h1>
        <span class="text-xs text-ink-subtle">Append-only, newest first. Nothing here can be edited.</span>
      </div>

      <VerifyChain />

      <form class="flex flex-wrap items-end gap-3" onSubmit={apply} aria-label="Audit filters">
        <label class="flex flex-col gap-0.5">
          Action (exact, or prefix ending in a dot)
          <input
            class={`${INPUT} w-56 font-mono`}
            value={draft.action}
            placeholder="case."
            autoComplete="off"
            onInput={(e) => setDraft({ ...draft, action: e.currentTarget.value })}
          />
        </label>
        <label class="flex flex-col gap-0.5">
          Result
          <select class={INPUT} value={draft.result} onChange={(e) => setDraft({ ...draft, result: e.currentTarget.value as Filters['result'] })}>
            <option value="">Any</option>
            <option value="ok">ok</option>
            <option value="denied">denied</option>
            <option value="failed">failed</option>
          </select>
        </label>
        <label class="flex flex-col gap-0.5">
          Actor id
          <input class={`${INPUT} w-72 font-mono`} value={draft.actor_id} autoComplete="off" onInput={(e) => setDraft({ ...draft, actor_id: e.currentTarget.value })} />
        </label>
        <label class="flex flex-col gap-0.5">
          Object id
          <input class={`${INPUT} w-72 font-mono`} value={draft.object_id} autoComplete="off" onInput={(e) => setDraft({ ...draft, object_id: e.currentTarget.value })} />
        </label>
        <Button size="sm" type="submit">
          Apply
        </Button>
        <Button size="sm" variant="neutral" onClick={clear}>
          Clear
        </Button>
      </form>

      {loaded.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the trail…" /> : null}
      {loaded.state === 'fail' ? <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} /> : null}
      {loaded.state === 'ok' && items.length === 0 ? (
        <ScreenState kind="empty" density="staff" heading="h2" title="No audit rows" body="Nothing matches these filters. Clear them to see the whole trail." />
      ) : null}

      {items.length > 0 ? (
        <div class="grid items-start gap-3 xl:grid-cols-[1fr_28rem]">
          <div class="overflow-x-auto border border-line">
            <table class="w-full border-collapse text-sm">
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
                {items.map((r) => (
                  <tr key={r.seq} aria-selected={open?.seq === r.seq} class={open?.seq === r.seq ? 'bg-info-soft' : 'hover:bg-sunken'}>
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
          {open ? <RowDetail row={open} onClose={() => setOpen(null)} /> : <p class="text-xs text-ink-subtle">Select a sequence number to see hashes and details.</p>}
        </div>
      ) : null}

      <div class="flex items-center gap-2">
        <Button size="sm" variant="neutral" disabled={trail.length <= 1} onClick={() => { setTrail(trail.slice(0, -1)); setOpen(null); }}>
          Newer
        </Button>
        <span class="text-xs text-ink-muted">Page {trail.length}</span>
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
      </div>
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
    <aside aria-label={`Audit row ${row.seq}`} class="border border-line-strong">
      <div class="flex items-center justify-between border-b border-line bg-sunken px-3 py-1.5">
        <h2 class="text-sm font-semibold uppercase tracking-wide">Row {row.seq}</h2>
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
        <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Details</h3>
        <pre class="max-h-72 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-2 font-mono text-xs">{JSON.stringify(row.details, null, 2)}</pre>
        {row.object_type === 'decision' && row.object_id ? (
          <p class="mt-2">
            <a href={`/staff/decisions/${row.object_id}`}>Open this decision</a>
          </p>
        ) : null}
      </div>
    </aside>
  );
}

function VerifyChain() {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Result<ChainOut> | null>(null);
  const run = async () => {
    setBusy(true);
    setOutcome(await call(api.GET('/v1/audit/verify')));
    setBusy(false);
  };
  return (
    <div class="flex flex-col gap-2 border border-line p-3">
      <div class="flex flex-wrap items-center gap-3">
        <Button size="sm" busy={busy} onClick={() => void run()}>
          Verify chain
        </Button>
        <span class="text-xs text-ink-muted">Recomputes every row hash from the start and reports the first row that does not match. This check is itself written to the trail.</span>
      </div>
      <div aria-live="polite">
        {outcome === null ? null : outcome.ok ? (
          outcome.data.ok ? (
            <p class="border border-primary bg-primary-soft px-3 py-2 text-primary-strong">
              Chain intact. {outcome.data.checked} rows checked, head sequence {outcome.data.head_seq}.
              <br />
              <span class="font-mono text-xs break-all">head hash {outcome.data.head_hash}</span>
            </p>
          ) : (
            <p role="alert" class="border border-danger bg-danger-soft px-3 py-2 text-danger">
              Chain broken. First broken row: {outcome.data.first_broken_seq ?? 'unknown'}. {outcome.data.problem ?? ''} {outcome.data.checked} rows checked before the break.
            </p>
          )
        ) : (
          <FailureState failure={outcome.failure} density="staff" heading="h2" onRetry={() => void run()} />
        )}
      </div>
    </div>
  );
}
