import type { ComponentChildren } from 'preact';
import { useRef, useState } from 'preact/hooks';
import { Badge } from '../ui';
import { demoActor, pageActor, send, trimmed, type Actor, type Query, type Trace } from './net';

export interface Step {
  label: string;
  trace: Trace;
}
export type Verdict = 'pass' | 'fail' | 'info';
export interface Outcome {
  verdict: Verdict;
  words: string[];
}

export interface Ctx {
  /** One real call. The trace appears on screen the moment it returns. */
  step(label: string, method: 'GET' | 'POST' | 'PUT', path: string, o: { as: Actor; body?: unknown; query?: Query }): Promise<{ trace: Trace; data: unknown; ok: boolean }>;
  /** The page's session when its role is one of `roles`, otherwise a demo account of the first role (signed in with its own token). */
  actor(roles: string[], pageRole: string): Promise<Actor | null>;
  /** Sign in as one demo account and show the sign-in as a step. */
  login(role: string, label: string, opts?: { tenant?: string; pick?: (a: { identifier: string }) => boolean }): Promise<Actor | null>;
}

const good = (s: number): boolean => s >= 200 && s < 300;

export function useRun() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(0);

  const run = async (body: (ctx: Ctx) => Promise<Outcome>): Promise<void> => {
    const mine = ++live.current;
    setSteps([]);
    setOutcome(null);
    setBusy(true);
    const push = (s: Step): void => {
      if (mine === live.current) setSteps((prev) => [...prev, s]);
    };
    const ctx: Ctx = {
      async step(label, method, path, o) {
        const { trace, data } = await send(method, path, o);
        push({ label, trace });
        return { trace, data, ok: good(trace.status) };
      },
      async actor(roles, pageRole) {
        if (roles.includes(pageRole)) return pageActor();
        const demo = await demoActor(roles[0] ?? '');
        if (!demo) return null;
        if (demo.trace) push({ label: `Sign in as the ${roles[0]} demo account (your role is ${pageRole || 'unknown'})`, trace: demo.trace });
        return demo.actor.token ? demo.actor : null;
      },
      async login(role, label, opts) {
        const demo = await demoActor(role, opts?.tenant ?? 'sindh-relief', opts?.pick);
        if (!demo) return null;
        if (demo.trace) push({ label, trace: demo.trace });
        return demo.actor.token ? demo.actor : null;
      },
    };
    try {
      const result = await body(ctx);
      if (mine === live.current) setOutcome(result);
    } catch (e) {
      if (mine === live.current) setOutcome({ verdict: 'fail', words: [`The card stopped: ${e instanceof Error ? e.message : 'unknown error'}.`] });
    } finally {
      if (mine === live.current) setBusy(false);
    }
  };
  return { steps, outcome, busy, run };
}

export function TraceBox({ step, n }: { step: Step; n: number }) {
  const t = step.trace;
  const tone = t.status >= 200 && t.status < 300 ? 'good' : t.status === 0 ? 'bad' : t.status >= 400 && t.status < 500 ? 'warn' : 'bad';
  return (
    <li class="border border-line">
      <details>
        <summary class="flex cursor-pointer flex-wrap items-center gap-2 bg-sunken px-2 py-1">
          <span class="font-mono text-xs text-ink-subtle">{n}</span>
          <span class="font-semibold">{step.label}</span>
          <span class="font-mono text-xs">
            {t.method} {t.path.length > 70 ? `${t.path.slice(0, 70)}…` : t.path}
          </span>
          <Badge tone={tone}>{t.status === 0 ? 'no answer' : t.status}</Badge>
          <span class="text-xs text-ink-subtle">{t.ms} ms</span>
        </summary>
        <div class="flex flex-col gap-1 p-2">
          <p class="text-xs text-ink-muted">
            Made as {t.actor}
            {t.requestId ? (
              <>
                , request id <span class="font-mono">{t.requestId}</span>
              </>
            ) : null}
          </p>
          {t.request !== undefined ? (
            <>
              <p class="text-xs font-semibold uppercase text-ink-muted">Request body</p>
              <pre class="max-h-40 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-1 font-mono text-xs">{trimmed(t.request, 900)}</pre>
            </>
          ) : null}
          <p class="text-xs font-semibold uppercase text-ink-muted">Response (trimmed)</p>
          <pre class="max-h-60 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-1 font-mono text-xs">{trimmed(t.response)}</pre>
        </div>
      </details>
    </li>
  );
}

const VERDICT = { pass: ['good', 'Worked as claimed'], fail: ['bad', 'Did not work as claimed'], info: ['info', 'Result'] } as const;

export function Card({
  n,
  title,
  claim,
  run: runState,
  onRun,
  disabled,
  disabledWhy,
  children,
  runLabel = 'Run',
}: {
  n: number | string;
  title: string;
  claim: string;
  run: ReturnType<typeof useRun>;
  onRun: () => void;
  disabled?: boolean;
  disabledWhy?: string;
  children?: ComponentChildren;
  runLabel?: string;
}) {
  const { steps, outcome, busy } = runState;
  const id = `lab-${n}`;
  return (
    <section aria-labelledby={id} class="flex flex-col gap-2 border border-line" data-testid={id}>
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-sunken px-3 py-1.5">
        <h2 id={id} class="text-sm font-semibold uppercase tracking-wide">
          {typeof n === 'number' ? `${n}. ` : ''}
          {title}
        </h2>
        <button type="button" class="h-8 rounded-sm border border-primary-strong bg-primary px-3 font-semibold text-white hover:bg-primary-strong disabled:opacity-60" disabled={busy || disabled} onClick={onRun}>
          {busy ? 'Running…' : runLabel}
        </button>
      </div>
      <div class="flex flex-col gap-2 px-3 pb-3">
        <p class="text-ink-muted">{claim}</p>
        {disabled && disabledWhy ? <p class="text-xs text-warning-ink">{disabledWhy}</p> : null}
        {children}
        {steps.length > 0 ? (
          <ol class="flex flex-col gap-1" aria-label="Calls made">
            {steps.map((s, i) => (
              <TraceBox key={i} step={s} n={i + 1} />
            ))}
          </ol>
        ) : null}
        {outcome ? (
          <div role="status" class={`border px-2 py-1 ${outcome.verdict === 'pass' ? 'border-primary bg-primary-soft' : outcome.verdict === 'fail' ? 'border-danger bg-danger-soft' : 'border-info-strong bg-info-soft'}`} data-testid={`${id}-result`} data-verdict={outcome.verdict}>
            <p class="mb-1">
              <Badge tone={VERDICT[outcome.verdict][0]}>{VERDICT[outcome.verdict][1]}</Badge>
            </p>
            {outcome.words.map((w, i) => (
              <p key={i} class={i > 0 ? 'mt-1' : ''}>
                {w}
              </p>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
