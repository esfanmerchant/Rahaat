import type { ComponentChildren } from 'preact';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure, Result } from '../shared/api/problem';
import { INPUT } from './ui';

/** The server's own words for a failure, plus its machine code. Rendered as text only. */
export function failureText(f: ApiFailure): string {
  if (f.kind === 'offline') return 'You are offline. Nothing was changed.';
  if (f.kind === 'network') return 'The request did not reach the server. Nothing was changed.';
  const p = f.problem;
  const base = p?.detail || p?.title || `The server answered ${f.status ?? 'with an error'}.`;
  const issues = p?.errors?.length ? ` (${p.errors.map((e) => `${e.field}: ${e.message}`).join('; ')})` : '';
  return `${base}${issues}`;
}

export const failureCode = (f: ApiFailure): string | undefined => f.problem?.code;

export type Flash = { tone: 'ok' | 'err'; text: string; code?: string | undefined; requestId?: string | undefined } | null;

export const flashFail = (f: ApiFailure): Flash => ({ tone: 'err', text: failureText(f), code: failureCode(f), requestId: f.problem?.request_id });

/** Inline outcome of an action. Errors use role=alert so a screen reader hears them. */
export function FlashLine({ flash }: { flash: Flash }) {
  if (!flash) return null;
  const bad = flash.tone === 'err';
  return (
    <p
      role={bad ? 'alert' : 'status'}
      class={`border px-2 py-1 text-sm ${bad ? 'border-danger bg-danger-soft text-danger' : 'border-primary bg-primary-soft text-primary-strong'}`}
    >
      {flash.text}
      {flash.code ? <span class="ms-2 font-mono text-xs">[{flash.code}]</span> : null}
      {flash.requestId ? <span class="ms-2 font-mono text-xs text-ink-subtle">request_id {flash.requestId}</span> : null}
    </p>
  );
}

interface PageData<T> {
  status: 'loading' | 'ok' | 'fail';
  items: T[];
  next: string | number | null;
  failure?: ApiFailure;
  loadingMore: boolean;
}

/** Cursor-paged list: first page on mount or when deps change, "Load more" appends. */
export function usePaged<T>(
  fetchPage: (cursor: string | number | undefined) => Promise<Result<{ items: T[]; next_cursor?: string | number | null }>>,
  deps: readonly unknown[],
) {
  const [state, setState] = useState<PageData<T>>({ status: 'loading', items: [], next: null, loadingMore: false });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);
  useEffect(() => {
    const mine = ++latest.current;
    setState((s) => (s.status === 'ok' ? s : { status: 'loading', items: [], next: null, loadingMore: false }));
    void fetchPage(undefined).then((res) => {
      if (mine !== latest.current) return;
      setState(
        res.ok
          ? { status: 'ok', items: res.data.items, next: res.data.next_cursor ?? null, loadingMore: false }
          : { status: 'fail', items: [], next: null, failure: res.failure, loadingMore: false },
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const more = useCallback(() => {
    const cursor = state.next;
    if (cursor === null || state.loadingMore) return;
    const mine = latest.current;
    setState((s) => ({ ...s, loadingMore: true }));
    void fetchPage(cursor).then((res) => {
      if (mine !== latest.current) return;
      setState((s) =>
        res.ok
          ? { status: 'ok', items: [...s.items, ...res.data.items], next: res.data.next_cursor ?? null, loadingMore: false }
          : { ...s, loadingMore: false, failure: res.failure },
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.next, state.loadingMore]);
  return { ...state, reload, more };
}

export function LoadMore({ next, busy, onMore }: { next: string | number | null; busy: boolean; onMore: () => void }) {
  if (next === null) return null;
  return (
    <button type="button" class="h-8 self-start rounded-sm border border-line-strong px-3 hover:bg-sunken disabled:opacity-60" disabled={busy} onClick={onMore}>
      {busy ? 'Loading…' : 'Load more'}
    </button>
  );
}

export const BTN = 'h-8 rounded-sm border border-line-strong px-3 hover:bg-sunken disabled:opacity-60';
export const BTN_PRIMARY = 'h-8 rounded-sm border border-primary-strong bg-primary px-3 font-semibold text-white hover:bg-primary-strong disabled:opacity-60';
export const BTN_DANGER = 'h-8 rounded-sm border border-danger px-3 font-semibold text-danger hover:bg-danger-soft disabled:opacity-60';

export const MIN_REASON = 5;

/**
 * A reason box that gates one action. The button stays disabled until the reason is long enough,
 * because the server writes it to the audit log and refuses anything shorter.
 */
export function ReasonAction({
  label,
  help,
  tone = 'neutral',
  busy,
  onSubmit,
  onCancel,
}: {
  label: string;
  help?: string;
  tone?: 'neutral' | 'primary' | 'danger';
  busy?: boolean;
  onSubmit: (reason: string) => void;
  onCancel?: () => void;
}) {
  const [reason, setReason] = useState('');
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const ok = reason.trim().length >= MIN_REASON;
  const cls = tone === 'primary' ? BTN_PRIMARY : tone === 'danger' ? BTN_DANGER : BTN;
  return (
    <form
      class="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) onSubmit(reason.trim());
      }}
    >
      <label class="flex flex-1 items-center gap-2">
        <span class="shrink-0">Reason</span>
        <input ref={ref} class={`${INPUT} min-w-48 flex-1`} value={reason} onInput={(e) => setReason(e.currentTarget.value)} aria-describedby="reason-note" />
      </label>
      <button type="submit" class={cls} disabled={!ok || busy}>
        {busy ? 'Working…' : label}
      </button>
      {onCancel ? (
        <button type="button" class={BTN} onClick={onCancel}>
          Cancel
        </button>
      ) : null}
      <span id="reason-note" class="basis-full text-xs text-ink-subtle">
        {help ?? 'Stored in the audit log.'} At least {MIN_REASON} characters ({reason.trim().length} so far).
      </span>
    </form>
  );
}

export function PageTitle({ children, aside }: { children?: ComponentChildren; aside?: ComponentChildren }) {
  return (
    <div class="flex flex-wrap items-center gap-3">
      {children}
      {aside}
    </div>
  );
}

export function copyText(text: string): void {
  try {
    void navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard may be blocked; the text is on screen anyway */
  }
}
