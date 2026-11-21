import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Badge, ConfBar, fmtAge, humanize, INPUT, TD, Th, slaText, useLoad, useNow, type CaseSummary } from '../ui';

type SortKey = 'priority' | 'confidence' | 'age';

/** Officer queue: one dense table, cases opened one at a time. No bulk actions exist here. */
export function QueuePage() {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/cases')), []);
  const now = useNow();
  // Priority 0 is the most urgent, so the default sort is ascending: urgent cases first.
  const [sortKey, setSortKey] = useState<SortKey>('priority');
  const [dir, setDir] = useState<'asc' | 'desc'>('asc');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [cursor, setCursor] = useState(0);
  const tableRef = useRef<HTMLTableElement>(null);

  const items: CaseSummary[] = loaded.state === 'ok' ? loaded.data.items : [];
  const statuses = useMemo(() => [...new Set(items.map((c) => c.status))].sort(), [items]);
  const kinds = useMemo(() => [...new Set(items.map((c) => c.kind))].sort(), [items]);

  const rows = useMemo(() => {
    const filtered = items.filter((c) => (!status || c.status === status) && (!kind || c.kind === kind));
    const value = (c: CaseSummary): number => (sortKey === 'priority' ? c.priority : sortKey === 'age' ? c.age_minutes : (c.confidence ?? -1));
    const sign = dir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => sign * (value(a) - value(b)) || a.id.localeCompare(b.id));
  }, [items, status, kind, sortKey, dir]);

  useEffect(() => {
    if (cursor >= rows.length) setCursor(Math.max(0, rows.length - 1));
  }, [rows.length, cursor]);

  const sortBy = (key: SortKey) => {
    if (key === sortKey) setDir(dir === 'asc' ? 'desc' : 'asc');
    else {
      setSortKey(key);
      // First click: most urgent, least confident, or oldest first.
      setDir(key === 'age' ? 'desc' : 'asc');
    }
  };

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
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Review queue
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value)}>
            <option value="">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <label class="flex items-center gap-1">
          Kind
          <select class={INPUT} value={kind} onChange={(e) => setKind(e.currentTarget.value)}>
            <option value="">All</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {humanize(k)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" class="h-8 rounded-sm border border-line-strong px-3 hover:bg-sunken" onClick={reload}>
          Refresh
        </button>
        <span class="ms-auto text-xs text-ink-subtle">j and k move, Enter opens. Cases are handled one at a time.</span>
      </div>

      {loaded.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the queue…" /> : null}
      {loaded.state === 'fail' ? <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} /> : null}
      {loaded.state === 'ok' && items.length === 0 ? (
        <ScreenState kind="empty" density="staff" heading="h2" title="The queue is empty" body="No cases are waiting for review. New cases appear here when the system hands one over." />
      ) : null}
      {loaded.state === 'ok' && items.length > 0 && rows.length === 0 ? (
        <ScreenState kind="empty" density="staff" heading="h2" title="No cases match these filters" body="Clear a filter to see more." />
      ) : null}

      {rows.length > 0 ? (
        <div class="overflow-x-auto border border-line">
          <table ref={tableRef} class="w-full border-collapse text-sm">
            <caption class="sr-only">Cases waiting for a person, sortable by priority, confidence and age</caption>
            <thead>
              <tr>
                <Th sort onSort={() => sortBy('priority')} active={sortKey === 'priority'} dir={dir}>Priority</Th>
                <Th>Kind</Th>
                <Th>Subject</Th>
                <Th sort onSort={() => sortBy('confidence')} active={sortKey === 'confidence'} dir={dir}>Confidence</Th>
                <Th>Why opened</Th>
                <Th>Status</Th>
                <Th sort onSort={() => sortBy('age')} active={sortKey === 'age'} dir={dir}>Age</Th>
                <Th>SLA</Th>
                <Th>Assignee</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => {
                const sla = slaText(c.sla_due_at, now);
                const current = i === cursor;
                return (
                  <tr
                    key={c.id}
                    data-row={i}
                    aria-selected={current}
                    class={current ? 'bg-info-soft outline outline-2 -outline-offset-2 outline-focus' : 'hover:bg-sunken'}
                    onClick={() => setCursor(i)}
                    onDblClick={() => route(`/staff/cases/${c.id}`)}
                  >
                    <td class={`${TD} font-mono tabular-nums`}>{c.priority}</td>
                    <td class={TD}>{humanize(c.kind)}</td>
                    <td class={TD}>
                      <a href={`/staff/cases/${c.id}`} class="font-semibold">
                        {c.subject_name ?? 'Unnamed subject'}
                      </a>
                    </td>
                    <td class={TD}>
                      <ConfBar value={c.confidence} />
                    </td>
                    <td class={TD}>{humanize(c.opened_reason)}</td>
                    <td class={TD}>
                      <Badge>{humanize(c.status)}</Badge>
                    </td>
                    <td class={`${TD} font-mono tabular-nums`}>{fmtAge(c.age_minutes)}</td>
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
      {loaded.state === 'ok' && loaded.data.next_cursor ? (
        <p class="text-xs text-ink-subtle">More cases exist than are shown (the list endpoint takes no cursor yet).</p>
      ) : null}
    </section>
  );
}
