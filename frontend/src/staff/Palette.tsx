import { Fragment } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import { navFor } from './nav';
import { theme, toggleTheme } from './theme';
import type { CaseSummary } from './ui';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HEX_PREFIX = /^[0-9a-f]{6,36}$/i;

interface Entry {
  id: string;
  group: 'Pages' | 'Cases' | 'Open by id' | 'Actions';
  label: string;
  hint?: string;
  run: () => void;
}

/**
 * Command palette (Ctrl or Cmd + K): jump to a page, or open a case by id, application id or the subject's name.
 * An ARIA combobox with a listbox; arrow keys move, Enter runs, Escape closes. Cases come from GET /v1/cases and
 * only for roles the server lets list them. Staff cannot look up a tracking code today (no endpoint; see REQUESTS).
 */
export function Palette({ role, open, onClose, onSignOut }: { role: string; open: boolean; onClose: () => void; onSignOut: () => void }) {
  const { route } = useLocation();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement as HTMLElement | null;
    setQ('');
    setActive(0);
    inputRef.current?.focus();
    let live = true;
    void call(api.GET('/v1/cases', { params: { query: { status: 'all', limit: 100 } } })).then((r) => {
      if (live) setCases(r.ok ? r.data.items : []);
    });
    return () => {
      live = false;
      opener.current?.focus?.();
    };
  }, [open]);

  const go = (path: string) => () => {
    onClose();
    route(path);
  };

  const entries = useMemo<Entry[]>(() => {
    const needle = q.trim().toLowerCase();
    const out: Entry[] = [];
    for (const item of navFor(role)) {
      if (!needle || item.label.toLowerCase().includes(needle) || item.slug.includes(needle)) {
        out.push({ id: `page-${item.slug}`, group: 'Pages', label: item.label, hint: `/staff/${item.slug}`, run: go(`/staff/${item.slug}`) });
      }
    }
    const raw = q.trim();
    if (UUID.test(raw)) {
      if (role === 'officer') out.push({ id: 'case-by-id', group: 'Open by id', label: 'Open case', hint: raw, run: go(`/staff/cases/${raw}`) });
      if (role === 'officer' || role === 'auditor') out.push({ id: 'decision-by-id', group: 'Open by id', label: 'Open decision', hint: raw, run: go(`/staff/decisions/${raw}`) });
    }
    if (needle && cases) {
      const hex = HEX_PREFIX.test(needle.replace(/-/g, ''));
      for (const c of cases) {
        const name = (c.subject_name ?? '').toLowerCase();
        const hit = name.includes(needle) || (hex && (c.id.startsWith(needle) || (c.application_id ?? '').startsWith(needle))) || c.opened_reason.includes(needle.replace(/ /g, '_'));
        if (hit && out.filter((e) => e.group === 'Cases').length < 6) {
          out.push({ id: `case-${c.id}`, group: 'Cases', label: c.subject_name ?? 'Unnamed subject', hint: `${c.kind.replace(/_/g, ' ')}, ${c.status.replace(/_/g, ' ')}, ${c.id.slice(0, 8)}`, run: go(`/staff/cases/${c.id}`) });
        }
      }
    }
    const acts: Entry[] = [
      { id: 'act-theme', group: 'Actions', label: theme.value === 'night' ? 'Switch to day theme' : 'Switch to night theme', run: () => { toggleTheme(); onClose(); } },
      { id: 'act-out', group: 'Actions', label: 'Sign out', run: () => { onClose(); onSignOut(); } },
    ];
    for (const a of acts) if (!needle || a.label.toLowerCase().includes(needle)) out.push(a);
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, cases, role, theme.value]);

  useEffect(() => {
    if (active >= entries.length) setActive(Math.max(0, entries.length - 1));
  }, [entries.length, active]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active, entries]);

  if (!open) return null;

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => (entries.length ? (a + 1) % entries.length : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => (entries.length ? (a - 1 + entries.length) % entries.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      entries[active]?.run();
    } else if (e.key === 'Tab') {
      e.preventDefault(); // the sheet holds focus in the field until it is closed
    }
  };

  let lastGroup = '';
  return (
    <div class="st-scrim flex items-start justify-center px-3 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" class="st-sheet w-full max-w-xl" onKeyDown={onKey}>
        <div class="flex items-center gap-2 border-b border-line px-3">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" class="shrink-0 text-ink-muted">
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-autocomplete="list"
            aria-label="Jump to a page or open a case"
            aria-activedescendant={entries[active] ? `opt-${entries[active]!.id}` : undefined}
            autoComplete="off"
            spellcheck={false}
            placeholder="Jump to a page, or type a case id or a name"
            class="h-11 min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-subtle focus:outline-none"
            value={q}
            onInput={(e) => {
              setQ(e.currentTarget.value);
              setActive(0);
            }}
          />
          <kbd class="st-kbd">Esc</kbd>
        </div>
        <ul id="palette-list" ref={listRef} role="listbox" aria-label="Results" class="max-h-[50vh] overflow-auto py-1">
          {entries.length === 0 ? (
            <li role="presentation" class="px-3 py-4 text-ink-muted">
              Nothing matches “{q}”. Pages, case ids, application ids and subject names are searched.
            </li>
          ) : null}
          {entries.map((e, i) => {
            const header = e.group !== lastGroup;
            lastGroup = e.group;
            return (
              <Fragment key={e.id}>
                {header ? (
                  <li key={`g-${e.group}`} role="presentation" class="px-3 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
                    {e.group}
                  </li>
                ) : null}
                <li
                  key={e.id}
                  id={`opt-${e.id}`}
                  role="option"
                  aria-selected={i === active}
                  class="st-opt flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5"
                  onMouseMove={() => active !== i && setActive(i)}
                  onClick={() => e.run()}
                >
                  <span class="truncate">{e.label}</span>
                  {e.hint ? <span class="truncate font-mono text-xs text-ink-subtle">{e.hint}</span> : null}
                </li>
              </Fragment>
            );
          })}
        </ul>
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-1.5 text-xs text-ink-subtle">
          <span><kbd class="st-kbd">Up</kbd> <kbd class="st-kbd">Down</kbd> move</span>
          <span><kbd class="st-kbd">Enter</kbd> open</span>
          <span class="ms-auto" aria-live="polite">{entries.length} result{entries.length === 1 ? '' : 's'}</span>
        </div>
      </div>
    </div>
  );
}
