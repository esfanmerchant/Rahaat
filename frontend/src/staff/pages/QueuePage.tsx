import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { LoadMore, usePaged } from '../kit';
import { Badge, ConfBar, fmtAge, humanize, INPUT, TD, Th, slaText, useNow, type CaseSummary } from '../ui';
import { AgeChip, HeatBar } from '../viz';

type SortKey = 'priority' | 'confidence' | 'age';
type StatusFilter = 'active' | 'all' | CaseSummary['status'];
type KindFilter = '' | CaseSummary['kind'];

const STATUSES: StatusFilter[] = ['active', 'open', 'assigned', 'in_review', 'waiting_proof', 'escalated', 'resolved', 'closed', 'all'];
const KINDS: CaseSummary['kind'][] = ['application_review', 'duplicate_review', 'document_review', 'complaint', 'appeal', 'correction', 'scam_review'];
const SORT_HELP: Record<SortKey, string> = {
  priority: 'most urgent first (0 is the most urgent)',
  confidence: 'least sure first',
  age: 'oldest first',
};

/**
 * Officer queue: one dense table, cases opened one at a time. Filters, sort and paging are the server's
 * (GET /v1/cases), so what is shown is what the queue holds, not what one page happened to contain.
 * No bulk actions exist here.
 */
export function QueuePage() {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const now = useNow();
  const [sortKey, setSortKey] = useState<SortKey>('priority');
  const [status, setStatus] = useState<StatusFilter>('active');
  const [kind, setKind] = useState<KindFilter>('');
  const [assignee, setAssignee] = useState('');
  const [cursor, setCursor] = useState(0);
  const tableRef = useRef<HTMLTableElement>(null);

  const list = usePaged<CaseSummary>(
    (after) =>
      call(
        api.GET('/v1/cases', {
          params: { query: { status, sort: sortKey, limit: 25, ...(kind ? { kind } : {}), ...(assignee ? { assignee } : {}), ...(after ? { cursor: String(after) } : {}) } },
        }),
      ),
    [status, kind, assignee, sortKey],
  );
  const rows = list.items;
  const reload = list.reload;
  const filtered = status !== 'active' || kind !== '' || assignee !== '';

  useEffect(() => {
    setCursor(0);
  }, [status, kind, assignee, sortKey]);
  useEffect(() => {
    if (cursor >= rows.length) setCursor(Math.max(0, rows.length - 1));
  }, [rows.length, cursor]);

  const onKeyDown = (event: KeyboardEvent) => {
    const el = event.target as HTMLElement;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return;
    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      setCursor((c) => Math.min(rows.length - 1, c + 1));
    } else if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (event.key === 'Enter' && el.tagName !== 'BUTTON' && el.tagName !== 'A') {
      const row = rows[cursor];
      if (row) route(`/staff/cases/${row.id}`);
    }
  };

  useEffect(() => {
    tableRef.current?.querySelector<HTMLElement>(`[data-row="${cursor}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  // j and k must work without first focusing the table, so listen on the document too.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const el = event.target as HTMLElement;
      if (el === document.body) onKeyDown(event);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  });

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3" onKeyDown={onKeyDown}>
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-xl font-black tracking-tight">
          Review queue
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value as StatusFilter)}>
            {STATUSES.map((st) => (
              <option key={st} value={st}>
                {st === 'active' ? 'Active (default)' : humanize(st)}
              </option>
            ))}
          </select>
        </label>
        <label class="flex items-center gap-1">
          Kind
          <select class={INPUT} value={kind} onChange={(e) => setKind(e.currentTarget.value as KindFilter)}>
            <option value="">All</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {humanize(k)}
              </option>
            ))}
          </select>
        </label>
        <label class="flex items-center gap-1">
          Assignee
          <select class={INPUT} value={assignee} onChange={(e) => setAssignee(e.currentTarget.value)}>
            <option value="">Anyone</option>
            <option value="me">Me</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </label>
        <label class="flex items-center gap-1">
          Sort
          <select class={INPUT} value={sortKey} onChange={(e) => setSortKey(e.currentTarget.value as SortKey)} aria-describedby="sort-help">
            <option value="priority">Priority</option>
            <option value="confidence">Confidence</option>
            <option value="age">Age</option>
          </select>
        </label>
        <button type="button" class="h-8 rounded-md border border-line-strong px-3 hover:bg-sunken" onClick={reload}>
          Refresh
        </button>
        <span class="ms-auto text-xs text-ink-subtle"><kbd class="st-kbd">j</kbd> <kbd class="st-kbd">k</kbd> move, <kbd class="st-kbd">Enter</kbd> opens. Cases are handled one at a time.</span>
      </div>

      <p id="sort-help" class="text-xs text-ink-subtle">
        Sorted by {sortKey}: {SORT_HELP[sortKey]}.
      </p>
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the queue…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={reload} /> : null}
      {list.status === 'ok' && rows.length === 0 ? (
        filtered ? (
          <ScreenState kind="empty" density="staff" heading="h2" title="No cases match these filters" body="Clear a filter to see more." />
        ) : (
          <ScreenState kind="empty" density="staff" heading="h2" title="The queue is empty" body="No cases are waiting for review. New cases appear here when the system hands one over." />
        )
      ) : null}

      {rows.length > 0 ? (
        <div class="st-panel max-h-[calc(100dvh-15rem)] min-h-40 overflow-auto">
          <table ref={tableRef} class="st-table w-full border-collapse text-sm">
            <caption class="sr-only">Cases, sorted by the server</caption>
            <thead>
              <tr>
                <Th>Priority</Th>
                <Th>Kind</Th>
                <Th>Subject</Th>
                <Th>Confidence</Th>
                <Th>Why opened</Th>
                <Th>Status</Th>
                <Th>Age</Th>
                <Th>SLA</Th>
                <Th>Assignee</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => {
                const sla = slaText(c.sla_due_at, now);
                const current = i === cursor;
                const [origin, ...rest] = c.opened_reason.includes('.') ? c.opened_reason.split('.') : ['', c.opened_reason];
                return (
                  <tr
                    key={c.id}
                    data-row={i}
                    style={{ '--i': i }}
                    aria-selected={current}
                    class={`st-row-in ${current ? 'st-cursor' : 'hover:bg-sunken'}`}
                    onClick={() => setCursor(i)}
                    onDblClick={() => route(`/staff/cases/${c.id}`)}
                  >
                    <td class={TD}>
                      <HeatBar priority={c.priority} />
                    </td>
                    <td class={`${TD} text-ink-muted`}>{humanize(c.kind)}</td>
                    <td class={TD}>
                      <a href={`/staff/cases/${c.id}`} class="font-semibold">
                        {c.subject_name ?? 'Unnamed subject'}
                      </a>
                    </td>
                    <td class={TD}>
                      <ConfBar value={c.confidence} />
                    </td>
                    <td class={TD}>
                      <span class="inline-flex flex-wrap items-center gap-1">
                        {origin ? <span class="text-xs uppercase tracking-wide text-ink-subtle">{origin}</span> : null}
                        <span class={`st-chip ${origin === 'guard' ? 'warn' : origin === 'rule' ? 'info' : ''}`}>{humanize(rest.join(' '))}</span>
                      </span>
                    </td>
                    <td class={TD}>
                      <Badge>{humanize(c.status)}</Badge>
                    </td>
                    <td class={TD}>
                      <AgeChip minutes={c.age_minutes} text={fmtAge(c.age_minutes)} />
                    </td>
                    <td class={TD}>
                      {c.sla_due_at ? <Badge tone={sla.overdue ? 'bad' : 'neutral'}>{sla.text}</Badge> : <span class="text-ink-subtle">none</span>}
                    </td>
                    <td class={TD}>
                      {c.assigned_to ? <span class="font-mono text-xs">{c.assigned_to.slice(0, 8)}</span> : <span class="text-ink-subtle">unassigned</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
    </section>
  );
}
