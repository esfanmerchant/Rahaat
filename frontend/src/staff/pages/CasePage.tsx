import { formatPhone } from '../phone';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { SectionTabs } from '../SectionTabs';
import { Badge, ConfBar, fmtAge, fmtTime, humanize, INPUT, TD, Th, useLoad, type CaseAction, type CaseDetail } from '../ui';
import { AgentPanel } from './AgentPanel';
import { DecisionAnatomy, ProvBadge } from './Anatomy';
import { DocumentsView, HandoffView, TraceView } from './parts';
import { Card, Check, Info } from './pg';

const ACTION_LABEL: Record<CaseAction, string> = {
  approve: 'Approve',
  reject: 'Reject',
  request_proof: 'Request proof',
  escalate: 'Escalate',
};
const ACTION_HELP: Record<CaseAction, string> = {
  approve: 'Approves the application.',
  reject: 'Rejects it. The citizen hears that a person checked.',
  request_proof: 'Asks the citizen for one more proof.',
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
    <article aria-labelledby="page-title" class="flex flex-col gap-3">
      <header class="pg-head pg-rise">
        <a href="/staff/queue" aria-label="Back to the queue" class="text-xs">
          &larr; Queue
        </a>
        <h1 id="page-title" ref={headingRef} tabIndex={-1}>
          {c.subject_name ?? 'Unnamed subject'}
        </h1>
        <Badge>{humanize(c.kind)}</Badge>
        <Badge tone="info">{humanize(c.status)}</Badge>
        <span class="st-chip" title="Priority (0 is most urgent)">
          P <span class="font-mono">{c.priority}</span>
        </span>
        <span class="st-chip" title="Confidence">
          <ConfBar value={c.confidence} />
        </span>
        <span class="st-chip" title="Open for">
          {fmtAge(c.age_minutes)}
        </span>
        <span class="st-chip warn" title="Opened because">
          {humanize(c.opened_reason)}
        </span>
        <span class="st-chip font-mono" title={c.id}>
          {c.id.slice(0, 8)}
        </span>
      </header>

      <ActionBar
        detail={c}
        onDone={(next, message) => {
          setFresh(next);
          setResult(message);
        }}
      />
      {result ? (
        <p role="status" class="pg-rise flex items-center gap-2 rounded-xl border border-primary bg-primary-soft px-3 py-2 text-primary-strong">
          <Check size={14} /> {result}
        </p>
      ) : null}

      <SectionTabs
        label="Case sections"
        sections={[
          { id: 'brief', label: 'Briefing' },
          { id: 'anatomy', label: 'Anatomy' },
          { id: 'assistant', label: 'Assistant' },
          { id: 'evidence', label: 'Evidence', badge: (c.document_checks ?? []).length },
          { id: 'history', label: 'History', badge: (c.events ?? []).length },
        ]}
      >
        {(tab) => {
          if (tab === 'brief') return <HandoffView handoff={c.handoff} />;
          if (tab === 'anatomy') {
            return c.decision ? (
              <DecisionAnatomy trace={c.decision} form={c.form} />
            ) : (
              <Card title="Anatomy">
                <p class="text-ink-muted">No automatic decision was recorded.</p>
              </Card>
            );
          }
          if (tab === 'assistant') return <AgentPanel caseId={c.id} />;
          if (tab === 'evidence') {
            return (
              <div class="flex flex-col gap-3">
                <FormTable detail={c} />
                <DocumentsView checks={c.document_checks ?? []} />
              </div>
            );
          }
          return (
            <div class="flex flex-col gap-3">
              <div class="pg-grid pg-21">
                <Card title="Events" i={0}>
                  <div class="pg-scroll" style={{ maxHeight: '22rem' }}>
                    {(c.events ?? []).length === 0 ? (
                      <p class="text-ink-muted">No events yet.</p>
                    ) : (
                      <table class="st-table w-full border-collapse">
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
                            <tr key={`${e.at}-${i}`} class="st-row-in" style={{ '--i': i }}>
                              <td class={`${TD} font-mono text-xs`}>{fmtTime(e.at)}</td>
                              <td class={TD}>{humanize(e.event)}</td>
                              <td class={TD}>{e.from_status || e.to_status ? `${e.from_status ?? 'none'} to ${e.to_status ?? 'none'}` : ''}</td>
                              <td class={TD}>{e.actor_name ?? 'system'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </Card>
                <NotesPanel detail={c} onChange={setFresh} />
              </div>
              <Card title="Trace" i={1} aside={c.decision ? <a href={`/staff/decisions/${c.decision.decision_id}`} class="text-xs">Decision viewer</a> : undefined}>
                {c.decision ? (
                  <details>
                    <summary class="cursor-pointer text-xs font-semibold text-ink-muted">Rule by rule</summary>
                    <div class="mt-2">
                      <TraceView trace={c.decision} />
                    </div>
                  </details>
                ) : (
                  <p class="text-ink-muted">No automatic decision.</p>
                )}
              </Card>
            </div>
          );
        }}
      </SectionTabs>
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
    <section aria-label="Actions" class="pg-decide pg-rise" style={{ '--i': 1 }}>
      <div class="pg-decide-row">
        <span class="pg-cap">Decide</span>
        {allowed.length === 0 ? <span class="text-ink-muted">No action in this status.</span> : null}
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
        <span class="ms-auto">
          <Info label="About decisions">Every action needs a written reason and is written to the audit chain.</Info>
        </span>
      </div>
      {pending ? (
        <form class="pg-decide-form" onSubmit={submit} onKeyDown={(e) => e.key === 'Escape' && close()} aria-label={`Confirm ${ACTION_LABEL[pending]}`}>
          <div class="flex flex-col gap-1">
            <p class="font-semibold">{ACTION_LABEL[pending]}</p>
            <p class="text-xs text-ink-muted" style={{ maxWidth: '13rem' }}>
              {ACTION_HELP[pending]}
            </p>
            {pending === 'request_proof' ? (
              <label class="flex items-center gap-2 text-xs">
                Proof
                <select class={INPUT} value={proof} onChange={(e) => setProof(e.currentTarget.value as (typeof PROOF_KINDS)[number])}>
                  {PROOF_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {humanize(k)}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          <label class="flex min-w-0 flex-1 flex-col gap-1" style={{ flexBasis: '22rem' }}>
            <span class="text-xs">
              Reason (required, {MIN_REASON}+ characters, audited)
            </span>
            <textarea
              ref={reasonRef}
              rows={2}
              maxLength={1000}
              required
              class="rounded-md border border-line-strong bg-paper p-2 text-sm"
              value={reason}
              aria-invalid={touched && tooShort}
              aria-describedby="reason-help"
              onInput={(e) => setReason(e.currentTarget.value)}
            />
            <span id="reason-help" class={touched && tooShort ? 'text-xs text-danger' : 'text-xs text-ink-subtle'} role={touched && tooShort ? 'alert' : undefined}>
              {touched && tooShort ? `At least ${MIN_REASON} characters.` : `${trimmed.length} of ${MIN_REASON} minimum`}
            </span>
          </label>
          <div class="flex flex-col gap-2">
            <Button size="sm" type="submit" busy={busy} variant={pending === 'reject' ? 'danger' : 'primary'}>
              Confirm {ACTION_LABEL[pending].toLowerCase()}
            </Button>
            <Button size="sm" variant="neutral" onClick={close} disabled={busy}>
              Cancel
            </Button>
          </div>
          {error ? (
            <p role="alert" class="w-full rounded-md border border-danger bg-danger-soft px-2 py-1 text-danger">
              {error}
            </p>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}

function FormTable({ detail }: { detail: CaseDetail }) {
  const form = detail.form;
  if (!form) {
    return (
      <Card title="Form">
        <p class="text-ink-muted">No application form.</p>
      </Card>
    );
  }
  const rows = Object.entries(form).filter(([k, v]) => typeof v === 'object' && v !== null && k !== 'language') as Array<
    [string, { value?: unknown; confidence?: number; provenance?: string; verified?: boolean }]
  >;
  return (
    <Card
      title="Form"
      i={0}
      aside={
        <span class="st-chip font-mono" title="Form language">
          {form.language}
        </span>
      }
    >
      <table class="st-table w-full border-collapse">
        <thead>
          <tr>
            <Th>Field</Th>
            <Th>Value</Th>
            <Th>Source</Th>
            <Th>Confidence</Th>
            <Th>Verified</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, f], i) => (
            <tr key={name} class="st-row-in" style={{ '--i': i }}>
              <td class={`${TD} font-mono text-xs`}>{name}</td>
              <td class={TD}>{f.value === null || f.value === undefined ? <span class="text-ink-subtle">unknown</span> : name === 'phone' ? <span class="rh-ltr">{formatPhone(String(f.value))}</span> : String(f.value)}</td>
              <td class={TD}>{f.provenance ? <ProvBadge prov={f.provenance} verified={f.verified} /> : <span class="text-ink-subtle">n/a</span>}</td>
              <td class={TD}>{f.value === null || f.value === undefined ? <span class="text-ink-subtle">n/a</span> : <ConfBar value={f.confidence} />}</td>
              <td class={TD}>
                {f.verified ? (
                  <span class="st-chip ok">
                    <Check /> verified
                  </span>
                ) : (
                  <span class="text-ink-subtle">no</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
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
    <Card title="Notes" i={1} aside={<span class="st-chip">{(detail.notes ?? []).length}</span>}>
      {(detail.notes ?? []).length === 0 ? (
        <p class="mb-3 text-ink-muted">No notes.</p>
      ) : (
        <ul class="mb-3 flex flex-col gap-2 overflow-auto" style={{ maxHeight: '10rem' }}>
          {(detail.notes ?? []).map((n) => (
            <li key={n.id} class="rounded-lg border border-line p-2">
              <p class="text-xs text-ink-muted">
                {n.author_name ?? n.author_kind} ({n.author_kind}) <span class="font-mono">{fmtTime(n.created_at)}</span>
              </p>
              {/* Notes can carry text from outside the system: plain text only. */}
              <p class="whitespace-pre-wrap break-words">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
      <form class="flex flex-col gap-2" onSubmit={add}>
        <label class="flex flex-col gap-1 text-xs">
          Add a note
          <textarea rows={2} maxLength={4000} class="rounded-md border border-line-strong bg-paper p-2 text-sm" value={body} onInput={(e) => setBody(e.currentTarget.value)} />
        </label>
        {error ? (
          <p role="alert" class="text-danger">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p role="status" class="text-primary-strong">
            Note added.
          </p>
        ) : null}
        <div>
          <Button size="sm" type="submit" variant="neutral" busy={busy}>
            Add note
          </Button>
        </div>
      </form>
    </Card>
  );
}
