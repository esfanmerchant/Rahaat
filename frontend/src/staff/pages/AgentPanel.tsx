import { useEffect, useRef, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { Button } from '../../shared/components/Button';
import { blockText, CONSEQUENCE, reasonText, resultLine, summarize, toolLabel } from '../agentText';
import { BTN, failureText } from '../kit';
import { CheckMark, CrossMark, Dialog, FailureLine } from '../loadview';
import { Badge, ConfBar, fmtTime, humanize, useLoad } from '../ui';
import { Card, Info } from './pg';

type Run = components['schemas']['RunOut'];
type Step = components['schemas']['StepOut'];

const MIN_REASON = 5;
const MAX_REASON = 1000;

type NodeTone = 'ok' | 'bad' | 'warn' | 'act' | 'idle' | 'spin';

/** Icons are drawn, never emoji. Each state has its own shape so colour is never the only signal. */
function NodeIcon({ tone, shape }: { tone: NodeTone; shape: 'check' | 'cross' | 'clock' | 'block' | 'alert' | 'dash' | 'arc' | 'dot' }) {
  const common = { fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' } as const;
  return (
    <span class={`st-node ${tone}`} aria-hidden="true">
      <svg width="14" height="14" viewBox="0 0 16 16">
        {shape === 'check' ? <path d="M3 8.5 6.5 12 13 4.5" {...common} /> : null}
        {shape === 'cross' ? <path d="M4 4l8 8M12 4l-8 8" {...common} /> : null}
        {shape === 'clock' ? (
          <>
            <circle cx="8" cy="8" r="5.6" {...common} />
            <path d="M8 4.8V8l2.2 1.4" {...common} />
          </>
        ) : null}
        {shape === 'block' ? (
          <>
            <circle cx="8" cy="8" r="5.6" {...common} />
            <path d="M4.2 11.8 11.8 4.2" {...common} />
          </>
        ) : null}
        {shape === 'alert' ? (
          <>
            <path d="M8 2.2 14 13H2z" {...common} />
            <path d="M8 6.5v3M8 11.3v.2" {...common} />
          </>
        ) : null}
        {shape === 'dash' ? (
          <>
            <circle cx="8" cy="8" r="5.6" {...common} />
            <path d="M5.5 8h5" {...common} />
          </>
        ) : null}
        {shape === 'arc' ? <path d="M8 2.4a5.6 5.6 0 1 1-5.6 5.6" {...common} /> : null}
        {shape === 'dot' ? <circle cx="8" cy="8" r="2.4" fill="currentColor" /> : null}
      </svg>
    </span>
  );
}

function codesOf(f: ApiFailure): string[] {
  const body = f.problem as unknown as { codes?: unknown; code?: string } | undefined;
  const codes = Array.isArray(body?.codes) ? (body?.codes as unknown[]).filter((c): c is string => typeof c === 'string') : [];
  return codes.length ? codes : body?.code ? [body.code] : [];
}

/** Admin and auditor read the run; only an officer starts, approves or rejects. The server enforces it either way. */
export function useStaffRole(): string {
  const s = session.value;
  return s.status === 'signed-in' ? s.active.role : '';
}

/** The assistant panel on the case page: start a run, read its steps, approve or reject the one proposed action. */
export function AgentPanel({ caseId }: { caseId: string }) {
  const role = useStaffRole();
  const isOfficer = role === 'officer';
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/cases/{case_id}/agent/runs', { params: { path: { case_id: caseId }, query: { limit: 5 } } })), [caseId]);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiFailure | null>(null);
  const [reusedNote, setReusedNote] = useState(false);

  useEffect(() => {
    if (loaded.state === 'ok') setRuns(loaded.data.items);
  }, [loaded]);
  useEffect(() => {
    setRuns(null);
    setReusedNote(false);
    setStartError(null);
  }, [caseId]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    setReusedNote(false);
    const res = await call(api.POST('/v1/cases/{case_id}/agent/runs', { params: { path: { case_id: caseId } } }));
    setStarting(false);
    if (!res.ok) return setStartError(res.failure);
    const run = res.data;
    setReusedNote(run.reused === true);
    setRuns((prev) => [run, ...(prev ?? []).filter((r) => r.id !== run.id)]);
  };

  const replace = (run: Run) => setRuns((prev) => (prev ?? []).map((r) => (r.id === run.id ? run : r)));
  const latest = runs?.[0];
  const earlier = runs?.slice(1) ?? [];

  return (
    <Card
      id="assistant"
      title="Assistant"
      class="pg-assist"
      aside={
        <>
          <span class="st-chip info" title="Planner">{latest ? latest.planner.type : 'local planner'}</span>
          <Info label="About the assistant">It reads the case and proposes one action. Nothing happens until an officer approves.</Info>
        </>
      }
    >
      <div class="flex flex-col gap-3">
        {loaded.state === 'loading' && runs === null ? (
          <div role="status" aria-label="Loading assistant runs" class="flex flex-col gap-2">
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
          </div>
        ) : null}
        {loaded.state === 'fail' && runs === null ? <FailureLine failure={loaded.failure} what="the assistant runs for this case" reload={reload} /> : null}

        {runs !== null ? (
          <div class="flex flex-wrap items-center gap-2">
            {isOfficer ? (
              latest && latest.status === 'waiting_approval' ? null : (
                <Button size="sm" variant="primary" busy={starting} onClick={() => void start()}>
                  {latest ? 'Run again' : 'Start assistant'}
                </Button>
              )
            ) : (
              <p class="st-chip info" title="Case text and the rationale are not shown to this role.">Read-only for {role || 'your role'}</p>
            )}
            {reusedNote ? (
              <p role="status" class="st-chip info">
                Run already waiting; shown.
              </p>
            ) : null}
          </div>
        ) : null}
        {startError ? (
          <p role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger">
            {startError.kind === 'forbidden'
              ? `Only an officer can start the assistant, on a case the person shared. ${startError.problem?.detail ?? ''}`
              : failureText(startError)}
            {startError.problem?.code ? <span class="ms-2 font-mono text-xs">[{startError.problem.code}]</span> : null}
          </p>
        ) : null}

        {runs !== null && runs.length === 0 ? (
          <p class="text-ink-muted">
            {isOfficer ? 'No run yet. Start one for a proposed next step.' : 'No assistant run.'}
          </p>
        ) : null}

        {latest ? <RunView key={latest.id} run={latest} role={role} onChange={replace} onReload={reload} /> : null}

        {earlier.length > 0 ? (
          <details class="text-xs">
            <summary class="cursor-pointer text-ink-muted">Earlier runs ({earlier.length})</summary>
            <div class="mt-2 flex flex-col gap-4">
              {earlier.map((r) => (
                <RunView key={r.id} run={r} role={role} onChange={replace} onReload={reload} compact />
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </Card>
  );
}

/** One run as a timeline: the read steps, then the proposed action or the abstention. Used by the case page and the read-only run page. */
export function RunView({ run, role, onChange, onReload, compact }: { run: Run; role: string; onChange: (r: Run) => void; onReload: () => void; compact?: boolean }) {
  const isOfficer = role === 'officer';
  const [deciding, setDeciding] = useState<{ step: Step; approve: boolean } | null>(null);
  const [live, setLive] = useState(run);
  useEffect(() => setLive(run), [run]);

  // A run that is still working is polled until it settles (a run is normally finished when it is returned).
  useEffect(() => {
    if (live.status !== 'running') return;
    const id = window.setInterval(() => {
      void call(api.GET('/v1/agent/runs/{agent_run_id}', { params: { path: { agent_run_id: live.id } } })).then((r) => {
        if (r.ok) onChange(r.data);
      });
    }, 1500);
    return () => window.clearInterval(id);
  }, [live.status, live.id, onChange]);

  const reads = live.steps.filter((s) => s.kind === 'read');
  const actions = live.steps.filter((s) => s.kind === 'action');
  const abstained = live.decision.abstained && actions.length === 0;
  const hasHiddenText = !isOfficer;

  return (
    <div class="flex flex-col gap-3" data-testid="agent-run">
      <RunHeader run={live} />
      {live.flags.length > 0 ? (
        <div role="alert" class="st-warnbar flex flex-wrap items-start gap-2 px-3 py-2" data-testid="agent-flags">
          <span class="st-chip warn">staff only</span>
          <span class="min-w-0 flex-1">
            Instruction-like text ignored.
            <span class="ms-2 inline-flex flex-wrap gap-1">
              {live.flags.map((f, i) => (
                <span key={`${f}-${i}`} class="st-chip warn font-mono">
                  {humanize(f).replace(':', ': ')}
                </span>
              ))}
            </span>
          </span>
        </div>
      ) : null}
      {hasHiddenText ? <span class="st-chip info" title="The rationale and read-step output contain case text, so the API does not return them to your role.">output hidden</span> : null}

      <div class="st-rail" role="list" aria-label="Assistant steps">
        {reads.map((s, i) => (
          <ReadStep key={s.id} step={s} index={i} showOutput={isOfficer} compact={compact} />
        ))}
        {live.status === 'running' ? <RunningStep index={reads.length} /> : null}
        {actions.map((s, i) => (
          <ActionStep key={s.id} step={s} index={reads.length + i} canDecide={isOfficer} onDecide={(approve) => setDeciding({ step: s, approve })} />
        ))}
        {abstained ? <AbstainStep run={live} index={reads.length} /> : null}
      </div>

      {deciding ? (
        <DecideDialog
          step={deciding.step}
          approve={deciding.approve}
          onClose={() => setDeciding(null)}
          onDone={(next) => {
            setLive(next);
            onChange(next);
          }}
          onBlocked={onReload}
        />
      ) : null}
    </div>
  );
}

function RunHeader({ run }: { run: Run }) {
  const p = run.planner;
  const outcome = run.steps.some((s) => s.status === 'blocked')
    ? { tone: 'bad' as const, text: 'Blocked by the action guard' }
    : run.status === 'running'
      ? { tone: 'info' as const, text: 'Working' }
      : run.status === 'waiting_approval'
        ? { tone: 'warn' as const, text: 'Waiting for an officer' }
        : run.outcome === 'approved'
          ? { tone: 'good' as const, text: 'Approved and done' }
          : run.outcome === 'rejected'
            ? { tone: 'neutral' as const, text: 'Proposal rejected by an officer' }
            : run.outcome === 'abstained'
              ? { tone: 'warn' as const, text: 'Assistant abstained' }
              : run.outcome === 'failed'
                ? { tone: 'bad' as const, text: 'Failed' }
                : { tone: 'neutral' as const, text: humanize(run.outcome) };
  return (
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <Badge tone={outcome.tone}>{outcome.text}</Badge>
      <span class="st-chip font-mono" title="Planner">{p.model_version}</span>
      {p.fallback_reason ? <span class="st-chip warn" title="Hosted planner not used">fallback: {humanize(p.fallback_reason)}</span> : null}
      <span class="st-chip" title="Decision confidence">
        <ConfBar value={run.decision.confidence} />
      </span>
      <span class="st-chip font-mono" title="Steps used of budget">
        {run.steps_used}/{run.step_budget}
      </span>
      <span class="text-ink-subtle" title="Started">{fmtTime(run.created_at)}</span>
    </div>
  );
}

function ReadStep({ step, index, showOutput, compact }: { step: Step; index: number; showOutput: boolean; compact?: boolean | undefined }) {
  const [open, setOpen] = useState(false);
  const failed = step.status === 'failed';
  const summary = showOutput ? summarize(step.tool, step.output as Record<string, unknown>) : 'Output hidden from your role.';
  const id = `read-${step.id}`;
  return (
    <div role="listitem" class="st-step" style={{ '--i': compact ? 0 : index }}>
      <NodeIcon tone={failed ? 'bad' : 'ok'} shape={failed ? 'alert' : 'check'} />
      <button
        type="button"
        class="flex w-full items-center gap-3 px-3 py-1 text-start"
        aria-expanded={open}
        aria-controls={id}
        disabled={!showOutput}
        onClick={() => setOpen((o) => !o)}
      >
        <span class="w-6 shrink-0 font-mono text-xs text-ink-subtle">{step.ordinal}</span>
        <span class="flex min-w-0 flex-1 items-center gap-2">
          <span class="shrink-0 font-semibold">{toolLabel(step.tool)}</span>
          <code class="st-chip font-mono shrink-0">{step.tool}</code>
          {failed ? <span class="st-chip bad">failed</span> : null}
          <span class="min-w-0 flex-1 truncate text-ink-muted" title={summary}>{summary}</span>
        </span>
        {showOutput ? <span class="shrink-0 text-xs text-ink-subtle">{open ? 'Hide' : 'Raw'}</span> : null}
      </button>
      {open && showOutput ? (
        <div id={id} class="border-t border-line px-3 py-2">
          <pre class="st-code" tabIndex={0} aria-label={`Output of ${step.tool}`}>
            {JSON.stringify(step.output, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function RunningStep({ index }: { index: number }) {
  return (
    <div role="listitem" class="st-step act" style={{ '--i': index }}>
      <NodeIcon tone="act" shape="arc" />
      <p role="status" class="px-3 py-2 text-ink-muted">
        Reading the case…
      </p>
    </div>
  );
}

function AbstainStep({ run, index }: { run: Run; index: number }) {
  return (
    <div role="listitem" class="st-step act" style={{ '--i': index }} data-testid="agent-abstained">
      <NodeIcon tone="warn" shape="dash" />
      <div class="flex flex-col gap-1 px-3 py-2">
        <p class="text-base font-bold">I am not sure; please review.</p>
        <p class="text-ink-muted">No action proposed. Start from the Briefing tab.</p>
        <p class="text-xs text-ink-muted">
          Why: {run.decision.reasons.length ? run.decision.reasons.map(reasonText).join(' ') : 'no reason recorded.'}
        </p>
      </div>
    </div>
  );
}

function ActionStep({ step, index, canDecide, onDecide }: { step: Step; index: number; canDecide: boolean; onDecide: (approve: boolean) => void }) {
  const waiting = step.status === 'waiting_approval';
  const done = step.status === 'done';
  const rejected = step.status === 'rejected';
  const blocked = step.status === 'blocked';
  const failed = step.status === 'failed';
  const out = step.output as Record<string, unknown>;
  const codes = Array.isArray(out['codes']) ? (out['codes'] as unknown[]).filter((c): c is string => typeof c === 'string') : step.block_codes ?? [];
  const args = Object.entries(step.args ?? {});
  const tone = waiting ? 'act' : done ? 'ok' : blocked || failed ? 'bad' : 'idle';
  const stateWord = waiting ? 'Waiting for approval' : done ? 'Approved and done' : rejected ? 'Rejected by an officer' : blocked ? 'Blocked by the action guard' : failed ? 'Approved but failed' : humanize(step.status);

  return (
    <div role="listitem" class={`pg-action ${waiting ? '' : done ? 'done' : blocked || failed ? 'bad' : 'idle'}`} style={{ '--i': index }} data-testid="agent-action" data-status={step.status}>
      <div class="flex items-start gap-3">
        <NodeIcon tone={tone} shape={waiting ? 'clock' : done ? 'check' : rejected ? 'cross' : blocked ? 'block' : failed ? 'alert' : 'dot'} />
      <div class="flex min-w-0 flex-1 flex-col gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="pg-cap">Proposed</span>
          <Badge tone={waiting ? 'warn' : done ? 'good' : blocked || failed ? 'bad' : 'neutral'}>{stateWord}</Badge>
          <span class="font-mono text-xs text-ink-subtle">step {step.ordinal}</span>
        </div>
        <p class="text-lg font-black">
          {toolLabel(step.tool)} <span class="st-chip font-mono">{step.tool}</span>
        </p>
        {args.length > 0 ? (
          <dl class="st-kv">
            {args.map(([k, v]) => (
              <>
                <dt key={`k-${k}`}>{humanize(k)}</dt>
                <dd key={`v-${k}`} class="font-mono text-xs">
                  {String(v)}
                </dd>
              </>
            ))}
          </dl>
        ) : (
          <p class="text-xs text-ink-subtle">
            No arguments {step.tool === 'approve_and_pay' ? <Info label="About the amount">The amount and the payee are never set by the assistant; the rule version decides the amount.</Info> : null}
          </p>
        )}
        {step.rationale ? (
          <div>
            <p class="pg-cap mb-1">Rationale</p>
            <p class="whitespace-pre-wrap break-words">{step.rationale}</p>
          </div>
        ) : null}

        {waiting && canDecide ? (
          <div class="flex flex-wrap items-center gap-2 border-t border-line pt-2">
            <Button size="sm" variant="primary" onClick={() => onDecide(true)} data-testid="agent-approve">
              Approve
            </Button>
            <Button size="sm" variant="danger" onClick={() => onDecide(false)} data-testid="agent-reject">
              Reject
            </Button>
            <Info label="What approving does">Each needs a written reason. {CONSEQUENCE[step.tool] ?? ''}</Info>
          </div>
        ) : null}
        {waiting && !canDecide ? <p class="text-xs text-ink-subtle">Officers only.</p> : null}

        {done ? <ApprovalResult out={out} step={step} /> : null}
        {rejected && step.approval ? (
          <p class="text-xs text-ink-muted">
            Rejected {fmtTime(step.approval.at)}. Reason: <span class="whitespace-pre-wrap break-words text-ink">{step.approval.reason}</span> Nothing ran.
          </p>
        ) : null}
        {blocked ? (
          <div role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger">
            <p class="font-semibold">Guard refused. Nothing ran.</p>
            <ul class="list-disc ps-5">
              {codes.length ? codes.map((c) => <li key={c}>{blockText(c)} <span class="font-mono text-xs">[{c}]</span></li>) : <li>No reason code was recorded.</li>}
            </ul>
          </div>
        ) : null}
        {failed ? <p class="text-danger">Approved but not finished ({humanize(String(out['error'] ?? 'unknown error'))}). Nothing changed. Use the Decide bar.</p> : null}
      </div>
      </div>
    </div>
  );
}

function ApprovalResult({ out, step }: { out: Record<string, unknown>; step: Step }) {
  const second = out['pending_second_approver'] === true;
  return (
    <div class="flex flex-col gap-1 border-t border-line pt-2">
      <p class="flex items-center gap-1 text-primary-strong">
        <CheckMark />
        <span>Result: {resultLine(out)}.</span>
      </p>
      {second ? (
        <p role="status" class="st-chip warn" style={{ height: 'auto', whiteSpace: 'normal', padding: '0.25rem 0.5rem' }}>
          The payment is above the department limit and waits for a second officer. <a href="/staff/approvals">Open the payment approvals queue</a>
        </p>
      ) : null}
      {step.approval ? (
        <p class="text-xs text-ink-muted">
          Approved {fmtTime(step.approval.at)}. Reason: <span class="whitespace-pre-wrap break-words text-ink">{step.approval.reason}</span>
        </p>
      ) : null}
    </div>
  );
}

/** The confirm dialog for approve and reject. A reason of 5 to 1000 characters is required, as the API requires. */
function DecideDialog({
  step,
  approve,
  onClose,
  onDone,
  onBlocked,
}: {
  step: Step;
  approve: boolean;
  onClose: () => void;
  onDone: (run: Run) => void;
  onBlocked: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<{ title: string; lines: string[]; code?: string | undefined } | null>(null);
  const [result, setResult] = useState<Run | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const trimmed = reason.trim();
  const bad = trimmed.length < MIN_REASON || trimmed.length > MAX_REASON;
  const verb = approve ? 'Approve' : 'Reject';

  const submit = async (e: Event) => {
    e.preventDefault();
    setTouched(true);
    if (bad || busy) {
      ref.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const path = { params: { path: { step_id: step.id } }, body: { reason: trimmed } };
    const res = await call(approve ? api.POST('/v1/agent/steps/{step_id}/approve', path) : api.POST('/v1/agent/steps/{step_id}/reject', path));
    setBusy(false);
    if (res.ok) {
      setResult(res.data);
      onDone(res.data);
      return;
    }
    const f = res.failure;
    const code = f.problem?.code;
    if (f.kind === 'conflict' && code && code !== 'step_not_pending' && code !== 'step_not_actionable') {
      const codes = codesOf(f);
      setError({ title: 'The action guard refused this step. Nothing ran.', lines: codes.map(blockText), code: codes.join(', ') });
      onBlocked();
    } else if (f.kind === 'conflict') {
      setError({ title: 'This step is no longer waiting.', lines: [f.problem?.detail ?? 'Another officer may have decided it already. The run has been reloaded.'], code });
      onBlocked();
    } else if (f.kind === 'forbidden') {
      const codes = codesOf(f);
      const specific = codes.filter((c) => c !== 'forbidden').map(blockText);
      setError({
        title: 'You may not approve this step.',
        lines: [
          'Only an officer can approve or reject assistant actions. Above the department payment limit it must be a different officer from the one who already approved this case.',
          ...specific,
          ...(f.problem?.detail ? [f.problem.detail] : []),
        ],
        code,
      });
    } else {
      setError({ title: 'The request did not complete.', lines: [failureText(f)], code });
    }
  };

  const finished = result !== null;
  const out = (result?.steps.find((s) => s.id === step.id)?.output ?? {}) as Record<string, unknown>;

  return (
    <Dialog title={`${verb} this action?`} onClose={onClose} busy={busy}>
      <div class="flex flex-col gap-1 border border-line bg-sunken px-3 py-2">
        <p class="font-semibold">
          {toolLabel(step.tool)} <span class="font-mono text-xs font-normal text-ink-subtle">{step.tool}</span>
        </p>
        {Object.entries(step.args ?? {}).map(([k, v]) => (
          <p key={k} class="font-mono text-xs">
            {k}: {String(v)}
          </p>
        ))}
        <p class="text-xs text-ink-muted">{approve ? (CONSEQUENCE[step.tool] ?? 'The action runs once, as you.') : 'Nothing runs. The proposal is closed and the case stays as it is.'}</p>
      </div>

      {finished ? (
        <div role="status" class="flex flex-col gap-2">
          <p class="flex items-center gap-1 text-primary-strong">
            {approve ? <CheckMark /> : <CrossMark />}
            <span>{approve ? `Approved. Result: ${resultLine(out)}.` : 'Rejected. Nothing ran.'}</span>
          </p>
          {out['pending_second_approver'] === true ? (
            <p class="st-warnbar px-2 py-1">
              The payment is above the department limit. A second officer must release it: <a href="/staff/approvals">open the payment approvals queue</a>.
            </p>
          ) : null}
          <div>
            <Button size="sm" variant="neutral" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      ) : (
        <form class="flex flex-col gap-2" onSubmit={(e) => void submit(e)} aria-label={`Confirm ${verb.toLowerCase()}`}>
          <label class="flex flex-col gap-1">
            <span>
              Reason (required, {MIN_REASON} to {MAX_REASON} characters; stored in the audit log)
            </span>
            <textarea
              ref={ref}
              rows={3}
              maxLength={MAX_REASON}
              class="rounded-sm border border-line-strong bg-paper p-2 text-sm"
              value={reason}
              aria-invalid={touched && bad}
              aria-describedby="agent-reason-help"
              onInput={(e) => setReason(e.currentTarget.value)}
              data-testid="agent-reason"
            />
          </label>
          <p id="agent-reason-help" class={touched && bad ? 'text-danger' : 'text-xs text-ink-subtle'} role={touched && bad ? 'alert' : undefined}>
            {touched && bad ? `A reason of ${MIN_REASON} to ${MAX_REASON} characters is required.` : `${trimmed.length} of ${MIN_REASON} characters minimum.`}
          </p>
          {error ? (
            <div role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger" data-testid="agent-error">
              <p class="font-semibold">{error.title}</p>
              <ul class="list-disc ps-5">
                {error.lines.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
              {error.code ? <p class="font-mono text-xs">[{error.code}]</p> : null}
            </div>
          ) : null}
          <div class="flex flex-wrap items-center gap-2">
            <Button size="sm" type="submit" busy={busy} variant={approve ? 'primary' : 'danger'} disabled={bad && touched}>
              Confirm {verb.toLowerCase()}
            </Button>
            <button type="button" class={BTN} onClick={onClose} disabled={busy}>
              {error ? 'Close' : 'Cancel'}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
