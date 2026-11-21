import { formatPhone } from '../phone';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Badge, ConfBar, fmtAge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad, type CaseAction, type CaseDetail } from '../ui';
import { DecisionAnatomy } from './Anatomy';
import { DocumentsView, HandoffView, TraceView } from './parts';

const ACTION_LABEL: Record<CaseAction, string> = {
  approve: 'Approve',
  reject: 'Reject',
  request_proof: 'Request proof',
  escalate: 'Escalate',
};
const ACTION_HELP: Record<CaseAction, string> = {
  approve: 'Approves the application. The reason is stored in the audit log.',
  reject: 'Rejects the application. The citizen is told a person checked it.',
  request_proof: 'Asks the citizen for one more proof. The case waits until it arrives.',
  escalate: 'Hands the case to a senior officer.',
};
const PROOF_KINDS = ['rahat_id', 'income_proof', 'other'] as const;
const MIN_REASON = 5;

function describe(failure: ApiFailure): string {
  const ref = failure.problem?.request_id ? ` (request_id ${failure.problem.request_id})` : '';
  switch (failure.kind) {
    case 'forbidden':
      return `You are not allowed to do this${ref}.`;
    case 'conflict':
      return `The case changed since you opened it. Reload and look again${ref}.`;
    case 'validation':
      return `The server rejected the input: ${failure.problem?.errors?.map((e) => e.message).join('; ') ?? failure.problem?.detail ?? 'check the fields'}${ref}.`;
    case 'offline':
      return 'You are offline. Nothing was sent. Your text is kept.';
    case 'not_found':
      return `The case no longer exists${ref}.`;
    default:
      return `The request failed${failure.status ? ` (${failure.status})` : ''}${ref}.`;
  }
}

export function CasePage({ id }: { id: string }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/cases/{case_id}', { params: { path: { case_id: id } } })), [id]);
  // The latest server copy after an action or a note.
  const [fresh, setFresh] = useState<CaseDetail | null>(null);
  const [result, setResult] = useState<string | null>(null);
  useEffect(() => {
    setFresh(null);
    setResult(null);
  }, [id]);

  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the case…" />;
  if (loaded.state === 'fail') {
    return (
      <div class="flex flex-col gap-2">
        <FailureState failure={loaded.failure} density="staff" onRetry={reload} />
        <a href="/staff/queue">Back to the queue</a>
      </div>
    );
  }
  const c = fresh ?? loaded.data;

  return (
    <article aria-labelledby="page-title" class="flex flex-col gap-4">
      <header class="flex flex-col gap-1">
        <a href="/staff/queue" class="text-xs">
          Back to the queue
        </a>
        <div class="flex flex-wrap items-center gap-3">
          <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-2xl font-black tracking-tight">
            {c.subject_name ?? 'Unnamed subject'}
          </h1>
          <Badge>{humanize(c.kind)}</Badge>
          <Badge tone="info">{humanize(c.status)}</Badge>
          <span class="text-xs">
            Priority <span class="font-mono">{c.priority}</span>
          </span>
          <span class="flex items-center gap-1 text-xs">
            Confidence <ConfBar value={c.confidence} />
          </span>
          <span class="text-xs">Open for {fmtAge(c.age_minutes)}</span>
          <span class="text-xs">Opened because: {humanize(c.opened_reason)}</span>
        </div>
        <Mono>{c.id}</Mono>
      </header>

      <ActionBar detail={c} onDone={(next, message) => { setFresh(next); setResult(message); }} />
      {result ? (
        <p role="status" class="border border-primary bg-primary-soft px-3 py-2 text-primary-strong">
          {result}
        </p>
      ) : null}

      <HandoffView handoff={c.handoff} />
      {c.decision ? <DecisionAnatomy trace={c.decision} form={c.form} /> : null}
      <FormTable detail={c} />
      <DocumentsView checks={c.document_checks ?? []} />
      <Section
        id="trace"
        title="Decision trace"
        aside={c.decision ? <a href={`/staff/decisions/${c.decision.decision_id}`} class="text-xs">Open in decision viewer</a> : undefined}
      >
        {c.decision ? <TraceView trace={c.decision} /> : <p class="text-ink-muted">No automatic decision was recorded for this case.</p>}
      </Section>
      <NotesPanel detail={c} onChange={setFresh} />
      <Section id="events" title="Case history">
        {(c.events ?? []).length === 0 ? (
          <p class="text-ink-muted">No events yet.</p>
        ) : (
          <table class="w-full border-collapse">
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Event</Th>
                <Th>Change</Th>
                <Th>By</Th>
              </tr>
            </thead>
            <tbody>
              {(c.events ?? []).map((e, i) => (
                <tr key={`${e.at}-${i}`}>
                  <td class={`${TD} font-mono text-xs`}>{fmtTime(e.at)}</td>
                  <td class={TD}>{humanize(e.event)}</td>
                  <td class={TD}>{e.from_status || e.to_status ? `${e.from_status ?? 'none'} to ${e.to_status ?? 'none'}` : ''}</td>
                  <td class={TD}>{e.actor_name ?? 'system'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </article>
  );
}

function ActionBar({ detail, onDone }: { detail: CaseDetail; onDone: (next: CaseDetail, message: string) => void }) {
  const [pending, setPending] = useState<CaseAction | null>(null);
  const [reason, setReason] = useState('');
  const [proof, setProof] = useState<(typeof PROOF_KINDS)[number]>('income_proof');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const allowed = detail.allowed_actions ?? [];
  const trimmed = reason.trim();
  const tooShort = trimmed.length < MIN_REASON;

  useEffect(() => {
    if (pending) reasonRef.current?.focus();
  }, [pending]);

  const close = () => {
    setPending(null);
    setError(null);
    setTouched(false);
    openerRef.current?.focus();
  };

  const submit = async (event: Event) => {
    event.preventDefault();
    setTouched(true);
    if (!pending || tooShort) {
      reasonRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const res = await call(
      api.POST('/v1/cases/{case_id}/actions', {
        params: { path: { case_id: detail.id } },
        body: { action: pending, reason: trimmed, ...(pending === 'request_proof' ? { proof_kind: proof } : {}) },
      }),
    );
    setBusy(false);
    if (res.ok) {
      onDone(res.data, `${ACTION_LABEL[pending]} recorded. Case status is now ${humanize(res.data.status)}.`);
      setPending(null);
      setReason('');
      setTouched(false);
    } else {
      setError(describe(res.failure));
    }
  };

  return (
    <section aria-label="Actions" class="st-panel st-lit p-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="font-semibold">Decide</span>
        {allowed.length === 0 ? <span class="text-ink-muted">No action is available for this case in its current status.</span> : null}
        {allowed.map((a) => (
          <Button
            key={a}
            size="sm"
            variant={a === 'reject' ? 'danger' : a === 'approve' ? 'primary' : 'neutral'}
            aria-pressed={pending === a}
            onClick={(e) => {
              openerRef.current = e.currentTarget;
              setPending(a);
              setError(null);
            }}
          >
            {ACTION_LABEL[a]}
          </Button>
        ))}
      </div>
      {pending ? (
        <form class="mt-3 flex max-w-2xl flex-col gap-2 border-t border-line pt-3" onSubmit={submit} onKeyDown={(e) => e.key === 'Escape' && close()} aria-label={`Confirm ${ACTION_LABEL[pending]}`}>
          <p class="font-semibold">Confirm: {ACTION_LABEL[pending]}</p>
          <p class="text-ink-muted">{ACTION_HELP[pending]}</p>
          {pending === 'request_proof' ? (
            <label class="flex items-center gap-2">
              Proof wanted
              <select class={INPUT} value={proof} onChange={(e) => setProof(e.currentTarget.value as (typeof PROOF_KINDS)[number])}>
                {PROOF_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {humanize(k)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label class="flex flex-col gap-1">
            <span>
              Reason (required, at least {MIN_REASON} characters; stored in the audit log)
            </span>
            <textarea
              ref={reasonRef}
              rows={3}
              maxLength={1000}
              required
              class="rounded-sm border border-line-strong bg-paper p-2 text-sm"
              value={reason}
              aria-invalid={touched && tooShort}
              aria-describedby="reason-help"
              onInput={(e) => setReason(e.currentTarget.value)}
            />
          </label>
          <p id="reason-help" class={touched && tooShort ? 'text-danger' : 'text-xs text-ink-subtle'} role={touched && tooShort ? 'alert' : undefined}>
            {touched && tooShort ? `A reason of at least ${MIN_REASON} characters is required.` : `${trimmed.length} of ${MIN_REASON} characters minimum.`}
          </p>
          {error ? (
            <p role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger">
              {error}
            </p>
          ) : null}
          <div class="flex gap-2">
            <Button size="sm" type="submit" busy={busy} variant={pending === 'reject' ? 'danger' : 'primary'}>
              Confirm {ACTION_LABEL[pending].toLowerCase()}
            </Button>
            <Button size="sm" variant="neutral" onClick={close} disabled={busy}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function FormTable({ detail }: { detail: CaseDetail }) {
  const form = detail.form;
  if (!form) {
    return (
      <Section id="form" title="Application form">
        <p class="text-ink-muted">This case has no application form attached.</p>
      </Section>
    );
  }
  const rows = Object.entries(form).filter(([k, v]) => typeof v === 'object' && v !== null && k !== 'language') as Array<
    [string, { value?: unknown; confidence?: number; provenance?: string; verified?: boolean }]
  >;
  return (
    <Section id="form" title="Application form" aside={<span class="text-xs text-ink-subtle">Form language {form.language}</span>}>
      <table class="w-full border-collapse">
        <thead>
          <tr>
            <Th>Field</Th>
            <Th>Value</Th>
            <Th>Provenance</Th>
            <Th>Confidence</Th>
            <Th>Verified</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, f]) => (
            <tr key={name}>
              <td class={`${TD} font-mono text-xs`}>{name}</td>
              <td class={TD}>{f.value === null || f.value === undefined ? <span class="text-ink-subtle">unknown</span> : name === 'phone' ? <span class="rh-ltr">{formatPhone(String(f.value))}</span> : String(f.value)}</td>
              <td class={TD}>{f.provenance ?? 'n/a'}</td>
              <td class={TD}>{f.value === null || f.value === undefined ? <span class="text-ink-subtle">n/a</span> : <ConfBar value={f.confidence} />}</td>
              <td class={TD}>{f.verified ? <Badge tone="good">verified</Badge> : <span class="text-ink-subtle">not verified</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function NotesPanel({ detail, onChange }: { detail: CaseDetail; onChange: (next: CaseDetail) => void }) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const add = async (event: Event) => {
    event.preventDefault();
    const text = body.trim();
    if (!text) {
      setError('Write something first.');
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(false);
    const res = await call(api.POST('/v1/cases/{case_id}/notes', { params: { path: { case_id: detail.id } }, body: { body: text } }));
    setBusy(false);
    if (res.ok) {
      onChange(res.data);
      setBody('');
      setSaved(true);
    } else {
      setError(describe(res.failure));
    }
  };

  return (
    <Section id="notes" title="Notes">
      {(detail.notes ?? []).length === 0 ? (
        <p class="mb-3 text-ink-muted">No notes yet.</p>
      ) : (
        <ul class="mb-3 flex flex-col gap-2">
          {(detail.notes ?? []).map((n) => (
            <li key={n.id} class="border border-line p-2">
              <p class="text-xs text-ink-muted">
                {n.author_name ?? n.author_kind} ({n.author_kind}) at <span class="font-mono">{fmtTime(n.created_at)}</span>
              </p>
              {/* Notes can carry text from outside the system: plain text only. */}
              <p class="whitespace-pre-wrap break-words">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
      <form class="flex max-w-2xl flex-col gap-2" onSubmit={add}>
        <label class="flex flex-col gap-1">
          Add a note
          <textarea rows={2} maxLength={4000} class="rounded-sm border border-line-strong bg-paper p-2 text-sm" value={body} onInput={(e) => setBody(e.currentTarget.value)} />
        </label>
        {error ? (
          <p role="alert" class="text-danger">
            {error}
          </p>
        ) : null}
        {saved ? <p role="status" class="text-primary-strong">Note added.</p> : null}
        <div>
          <Button size="sm" type="submit" variant="neutral" busy={busy}>
            Add note
          </Button>
        </div>
      </form>
    </Section>
  );
}
