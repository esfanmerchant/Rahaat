import type { ComponentChildren } from 'preact';
import { useEffect, useRef } from 'preact/hooks';
import type { ApiFailure } from '../shared/api/problem';
import './wpe.css';
import { failureText } from './kit';
import type { Loaded } from './ui';

/**
 * Shared pieces of the Phase 3 staff screens: a body that shows every non-success state in plain words
 * (loading skeleton, 403, offline, error), a modal dialog with a focus trap, and two drawn marks.
 */

export function LoadView<T>({
  state,
  reload,
  what,
  rows = 4,
  children,
}: {
  state: Loaded<T>;
  reload: () => void;
  /** What the panel shows, for the sentences that explain a refusal. */
  what: string;
  rows?: number;
  children: (data: T) => ComponentChildren;
}) {
  if (state.state === 'loading') {
    return (
      <div role="status" aria-label={`Loading ${what}`} class="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} class="rh-skeleton h-7" />
        ))}
      </div>
    );
  }
  if (state.state === 'fail') return <FailureLine failure={state.failure} what={what} reload={reload} />;
  return <>{children(state.data)}</>;
}

export function FailureLine({ failure: f, what, reload }: { failure: ApiFailure; what: string; reload: () => void }) {
  if (f.kind === 'forbidden') {
    return (
      <p role="status" class="flex flex-wrap items-start gap-2 text-ink-muted">
        <span class="st-chip warn">403</span>
        <span>
          Your role cannot read {what}. {f.problem?.detail ?? ''} The server decides this; nothing is made up in its place.
        </span>
      </p>
    );
  }
  if (f.kind === 'offline' || f.kind === 'network') {
    return (
      <p role="status" class="flex flex-wrap items-center gap-2 text-ink-muted">
        <span class="st-chip warn">offline</span>
        <span>{f.kind === 'offline' ? 'You are offline.' : 'The server did not answer.'} Nothing was changed.</span>
        <button type="button" class="st-chip info hover:brightness-125" onClick={reload}>
          Try now
        </button>
      </p>
    );
  }
  return (
    <p role="alert" class="flex flex-wrap items-center gap-2 text-danger">
      <span class="st-chip bad">error</span>
      <span>{failureText(f)}</span>
      {f.problem?.request_id ? <span class="font-mono text-xs text-ink-subtle">request_id {f.problem.request_id}</span> : null}
      <button type="button" class="st-chip info hover:brightness-125" onClick={reload}>
        Try again
      </button>
    </p>
  );
}

/** An empty list, in words, with the next step. */
export function Empty({ title, body, children }: { title: string; body: string; children?: ComponentChildren }) {
  return (
    <div role="status" class="flex flex-col items-center gap-1 border border-dashed border-line-strong p-4 text-center">
      <p class="font-semibold text-ink">{title}</p>
      <p class="text-ink-muted">{body}</p>
      {children}
    </div>
  );
}

export function Dialog({
  title,
  onClose,
  busy,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
  children?: ComponentChildren;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null;
    sheet.current?.querySelector<HTMLElement>('textarea, input, select')?.focus();
    return () => opener.current?.focus?.();
  }, []);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && !busy) {
      e.stopPropagation();
      onClose();
    } else if (e.key === 'Tab' && sheet.current) {
      const items = Array.from(sheet.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), textarea, input, select'));
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (!firstEl || !lastEl) return;
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    }
  };
  return (
    <div class="st-scrim flex items-start justify-center px-3 pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div ref={sheet} role="dialog" aria-modal="true" aria-label={title} class={`st-sheet st-dialog w-full ${wide ? 'max-w-2xl' : 'max-w-lg'}`} onKeyDown={onKey}>
        <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
          <h2 class="text-base font-bold">{title}</h2>
          <kbd class="st-kbd">Esc</kbd>
        </div>
        <div class="flex flex-col gap-3 p-4">{children}</div>
      </div>
    </div>
  );
}

/** A drawn check mark and cross, so no emoji is ever used as an icon. */
export function CheckMark({ size = 14, label }: { size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} class="shrink-0">
      <path d="M3 8.5 6.5 12 13 4.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  );
}

export function CrossMark({ size = 14, label }: { size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} class="shrink-0">
      <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
    </svg>
  );
}
