import { useEffect, useMemo, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, failureText, LoadMore, usePaged } from '../kit';
import { CheckMark, Dialog, Empty, FailureLine, LoadView } from '../loadview';
import { Badge, fmtAge, fmtTime, humanize, Mono, Section, TD, Th, useLoad, useNow } from '../ui';

type Row = components['schemas']['AppealStaffOut'];
type Detail = components['schemas']['AppealStaffDetail'];
type Payment = components['schemas']['PaymentOut'];

const STATUSES = ['open', 'upheld', 'overturned', 'withdrawn', 'all'] as const;
type StatusFilter = (typeof STATUSES)[number];
const MIN_REASON = 5;
const MAX_REASON = 1000;
const rs = (n: number) => `Rs ${n.toLocaleString('en-US')}`;

const CANNOT_TEXT: Record<string, string> = {
  appeal_same_officer: 'You reviewed, decided or second-approved the first decision on this application. A different officer must decide the appeal.',
  appeal_not_open: 'This appeal has already been decided.',
};
const cannotText = (code: string | null | undefined): string => (code ? (CANNOT_TEXT[code] ?? humanize(code)) : 'The server did not say why.');

/** How long an appeal has waited, warming toward its due date. Open ones use the due date; decided ones are calm. */
function AppealAge({ row, now }: { row: Row; now: number }) {
  const minutes = Math.max(0, Math.floor((now - new Date(row.created_at).getTime()) / 60000));
  const open = row.status === 'open';
  const due = row.due_at ? new Date(row.due_at).getTime() : null;
  const left = due === null ? null : due - now;
  const level = !open ? 0 : left !== null && left < 0 ? 3 : left !== null && left < 24 * 3600_000 ? 2 : minutes >= 2 * 1440 ? 1 : 0;
  const title = open && left !== null ? (left < 0 ? `Overdue by ${fmtAge(Math.floor(-left / 60000))}` : `Due in ${fmtAge(Math.floor(left / 60000))}`) : `Filed ${fmtAge(minutes)} ago`;
  return (
    <span class={`st-chip st-age-${level} rh-num font-mono`} title={title}>
      {fmtAge(minutes)}
      {open && left !== null && left < 0 ? ' overdue' : ''}
    </span>
  );
}

/** Appeals against a rejection, oldest first. An officer who had no part in the first decision decides; the server checks. */
export function AppealsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = session.value.status === 'signed-in' ? session.value.active.role : '';
  const now = useNow();
  const [status, setStatus] = useState<StatusFilter>('open');
  const [sel, setSel] = useState<string | null>(null);
  const [result, setResult] = useState<{ detail: Detail; payment: Payment | null | 'unknown' } | null>(null);
  const list = usePaged<Row>((cursor) => call(api.GET('/v1/appeals', { params: { query: { status, limit: 50, ...(cursor ? { cursor: String(cursor) } : {}) } } })), [status]);
  const rows = useMemo(() => [...list.items].sort((a, b) => a.created_at.localeCompare(b.created_at)), [list.items]);

  useEffect(() => {
    if (list.status === 'ok' && (sel === null || !rows.some((r) => r.id === sel))) setSel(rows[0]?.id ?? null);
  }, [list.status, rows, sel]);

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Appeals
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink" value={status} onChange={(e) => setStatus(e.currentTarget.value as StatusFilter)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button type="button" class={BTN} onClick={list.reload}>
          Refresh
        </button>
        <span class="text-xs text-ink-subtle">Oldest first. {role === 'auditor' ? 'Read-only for the auditor, with no personal data.' : 'A different officer from the first decision decides.'}</span>
      </div>

      <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <Section id="queue" title={`${status === 'all' ? 'All' : humanize(status)} appeals`} aside={<span class="font-mono text-xs text-ink-subtle">{rows.length} shown</span>}>
          {list.status === 'loading' ? (
            <div role="status" aria-label="Loading appeals" class="flex flex-col gap-2">
              <div class="rh-skeleton h-7" />
              <div class="rh-skeleton h-7" />
              <div class="rh-skeleton h-7" />
              <div class="rh-skeleton h-7" />
            </div>
          ) : null}
          {list.status === 'fail' && list.failure ? <FailureLine failure={list.failure} what="the appeals queue" reload={list.reload} /> : null}
          {list.status === 'ok' && rows.length === 0 ? (
            <Empty title={status === 'open' ? 'No open appeals' : 'No appeals here'} body={status === 'open' ? 'When a citizen appeals a rejection it appears here, oldest first.' : 'Nothing matches this status.'} />
          ) : null}
          {list.status === 'ok' && rows.length > 0 ? (
            <div class="overflow-auto">
              <table class="st-table w-full border-collapse text-sm" data-testid="appeals">
                <thead>
                  <tr>
                    <Th>Waiting</Th>
                    <Th>Tracking code</Th>
                    <Th>Status</Th>
                    <Th>Filed</Th>
                    <Th>Due</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.id} class={`st-row-in ${sel === r.id ? 'st-cursor' : ''}`} style={{ '--i': i }}>
                      <td class={TD}>
                        <AppealAge row={r} now={now} />
                      </td>
                      <td class={TD}>
                        <button type="button" class="font-mono text-xs underline" aria-pressed={sel === r.id} onClick={() => { setResult(null); setSel(r.id); }}>
                          {r.tracking_code ?? r.application_id.slice(0, 8)}
                        </button>
                      </td>
                      <td class={TD}>
                        <Badge tone={r.status === 'open' ? 'warn' : r.status === 'overturned' ? 'good' : 'neutral'}>{r.status}</Badge>
                      </td>
                      <td class={`${TD} font-mono text-xs`}>{fmtTime(r.created_at)}</td>
                      <td class={`${TD} font-mono text-xs`}>{r.due_at ? fmtTime(r.due_at) : 'n/a'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
        </Section>

        {result ? (
          <DecisionResult
            result={result}
            onNext={() => {
              setResult(null);
              setSel(null);
            }}
          />
        ) : sel ? (
          <AppealDetail key={sel} id={sel} role={role} onDecided={(detail, payment) => { setResult({ detail, payment }); list.reload(); }} />
        ) : <Section id="detail" title="Appeal">{list.status === 'ok' ? <p class="text-ink-muted">Select an appeal to read it.</p> : <div class="rh-skeleton h-24" />}</Section>}
      </div>
    </section>
  );
}

function AppealDetail({ id, role, onDecided }: { id: string; role: string; onDecided: (d: Detail, payment: Payment | null | 'unknown') => void }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/appeals/{appeal_id}', { params: { path: { appeal_id: id } } })), [id]);
  const [dialog, setDialog] = useState(false);

  return (
    <Section id="detail" title="Appeal">
      <LoadView state={loaded} reload={reload} what={role === 'auditor' ? 'the detail of this appeal (an auditor sees the queue, not the citizen file)' : 'this appeal'} rows={5}>
        {(loadedDetail) => {
          const d = loadedDetail;
          const decided = d.status !== 'open';
          return (
            <div class="flex flex-col gap-3" data-testid="appeal-detail">
              <div class="flex flex-wrap items-center gap-2">
                <Badge tone={d.status === 'open' ? 'warn' : d.status === 'overturned' ? 'good' : 'neutral'}>{d.status}</Badge>
                <span class="text-xs text-ink-muted">Filed {fmtTime(d.created_at)}, {d.age_days} day(s) ago</span>
                {d.due_at ? <span class="text-xs text-ink-muted">Due {fmtTime(d.due_at)}</span> : null}
              </div>

              <dl class="st-kv">
                <dt>What is contested</dt>
                <dd>
                  The rejection of application <Mono>{d.application_id}</Mono>
                  {d.tracking_code ? <> (tracking code <Mono>{d.tracking_code}</Mono>)</> : null}
                </dd>
                <dt>Original outcome</dt>
                <dd>
                  <span class="font-semibold">{d.original_outcome ? humanize(d.original_outcome) : 'not recorded'}</span>
                  {(d.original_reasons ?? []).length > 0 ? <span class="text-ink-muted"> because {(d.original_reasons ?? []).map(humanize).join('; ')}</span> : null}
                </dd>
                <dt>Records</dt>
                <dd class="flex flex-wrap gap-3">
                  {d.case_id && role === 'officer' ? <a href={`/staff/cases/${d.case_id}`}>Open the case</a> : null}
                  {d.decision_id && (role === 'officer' || role === 'auditor') ? <a href={`/staff/decisions/${d.decision_id}`}>Open the original decision</a> : null}
                  {!d.case_id && !d.decision_id ? <span class="text-ink-subtle">none linked</span> : null}
                </dd>
              </dl>

              <div class="border border-line bg-sunken px-3 py-2">
                <p class="text-xs uppercase tracking-widest text-ink-muted">The citizen's reason (their own words)</p>
                {/* The citizen's text is untrusted: shown as text only. */}
                <p class="mt-1 whitespace-pre-wrap break-words text-base" data-testid="appeal-reason">
                  {d.reason ?? <span class="text-ink-subtle">No reason is shown. The person's consent may not allow staff to read it.</span>}
                </p>
              </div>

              {decided ? (
                <div role="status" class="flex flex-col gap-1">
                  <p class="flex items-center gap-1 text-primary-strong">
                    <CheckMark />
                    <span>
                      Decided: <span class="font-semibold">{d.outcome ?? d.status}</span>
                      {d.resolved_at ? `, ${fmtTime(d.resolved_at)}` : ''}.
                    </span>
                  </p>
                </div>
              ) : role !== 'officer' ? (
                <p class="st-chip info" style={{ height: 'auto', whiteSpace: 'normal', padding: '0.25rem 0.6rem' }}>
                  Read-only for the {role || 'current'} role. Only an officer can decide an appeal.
                </p>
              ) : d.can_decide ? (
                <div class="flex flex-wrap items-center gap-2">
                  <button type="button" class={BTN_PRIMARY} onClick={() => setDialog(true)} data-testid="appeal-decide">
                    Decide this appeal
                  </button>
                  <span class="text-xs text-ink-subtle">You may decide it: you had no part in the first decision.</span>
                </div>
              ) : (
                <div class="flex flex-col gap-1" data-testid="appeal-cannot">
                  <div class="flex flex-wrap items-center gap-2">
                    <button type="button" class={BTN} disabled>
                      Decide this appeal
                    </button>
                    <span class="st-chip warn">you cannot decide this one</span>
                  </div>
                  <p class="text-warning-ink">{cannotText(d.cannot_decide_reason)}</p>
                </div>
              )}
            </div>
          );
        }}
      </LoadView>
      {dialog ? (
        <DecideDialog
          id={id}
          onClose={() => setDialog(false)}
          onDone={async (detail) => {
            setDialog(false);
            let payment: Payment | null | 'unknown' = null;
            if (detail.status === 'overturned') {
              const pays = await call(api.GET('/v1/payments', { params: { query: { limit: 100 } } }));
              payment = pays.ok ? (pays.data.items.find((p) => p.application_id === detail.application_id) ?? null) : 'unknown';
            }
            onDecided(detail, payment);
          }}
        />
      ) : null}
    </Section>
  );
}

function DecisionResult({ result, onNext }: { result: { detail: Detail; payment: Payment | null | 'unknown' }; onNext: () => void }) {
  const d = result.detail;
  return (
    <Section id="detail" title="Decision recorded">
      <div class="flex flex-col gap-3" data-testid="appeal-result" role="status">
        <p class="flex items-center gap-2 text-base">
          <span class="text-primary-strong">
            <CheckMark size={18} />
          </span>
          <span>
            Appeal <Badge tone={d.status === 'overturned' ? 'good' : 'neutral'}>{d.status}</Badge> {d.resolved_at ? <span class="font-mono text-xs text-ink-muted">{fmtTime(d.resolved_at)}</span> : null}
          </span>
        </p>
        {d.status === 'overturned' ? (
          <>
            <p>The rejection is reversed. The application is approved and the citizen has been told.</p>
            <PaymentLine payment={result.payment} />
          </>
        ) : (
          <p>The first answer stays. The citizen has been told a person checked it again.</p>
        )}
        <p class="text-xs text-ink-subtle">
          Application <Mono>{d.application_id}</Mono>. Your reason is in the audit log.
        </p>
        <div>
          <button type="button" class={BTN_PRIMARY} onClick={onNext}>
            Next appeal
          </button>
        </div>
      </div>
    </Section>
  );
}

function PaymentLine({ payment }: { payment: Payment | null | 'unknown' }) {
  if (payment === 'unknown') return <p class="text-xs text-ink-muted">The application is approved and a payment was requested. The payment list could not be read just now.</p>;
  if (payment === null) return <p class="text-xs text-ink-muted">The application is approved. No payment row was found yet for it.</p>;
  const waiting = payment.status === 'pending_approval';
  return (
    <p class="flex flex-wrap items-center gap-2" data-testid="appeal-payment">
      <span>Application approved. Payment {rs(payment.amount_pkr)}:</span>
      <Badge tone={payment.status === 'settled' ? 'good' : waiting ? 'warn' : 'neutral'}>{humanize(payment.status)}</Badge>
      {waiting ? (
        <span class="text-xs text-ink-muted">
          It is above the department limit and needs a second officer, not you. <a href="/staff/approvals">Open the payment approvals queue</a>
        </span>
      ) : null}
    </p>
  );
}

function failureLines(f: ApiFailure): { title: string; lines: string[]; code?: string | undefined } {
  const code = f.problem?.code;
  if (f.kind === 'forbidden') {
    if (code === 'appeal_same_officer') return { title: 'You cannot decide this appeal.', lines: [CANNOT_TEXT['appeal_same_officer'] ?? ''], code };
    if (code === 'consent_required') return { title: 'The citizen has withdrawn consent.', lines: ['Staff may not read this application any more, so the appeal cannot be decided until consent is given again.'], code };
    return { title: 'The server refused this.', lines: ['Only an officer can decide an appeal.', ...(f.problem?.detail ? [f.problem.detail] : [])], code };
  }
  if (f.kind === 'conflict') return { title: 'This appeal cannot be decided now.', lines: [f.problem?.detail ?? 'It may already be decided. Refresh the queue.'], code };
  return { title: 'The request did not complete.', lines: [failureText(f)], code };
}

function DecideDialog({ id, onClose, onDone }: { id: string; onClose: () => void; onDone: (d: Detail) => void | Promise<void> }) {
  const [outcome, setOutcome] = useState<'upheld' | 'overturned' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<ReturnType<typeof failureLines> | null>(null);
  const trimmed = reason.trim();
  const bad = outcome === null || trimmed.length < MIN_REASON || trimmed.length > MAX_REASON;

  const submit = async (e: Event) => {
    e.preventDefault();
    setTouched(true);
    if (bad || busy || outcome === null) return;
    setBusy(true);
    setError(null);
    const res = await call(api.POST('/v1/appeals/{appeal_id}/decide', { params: { path: { appeal_id: id } }, body: { outcome, reason: trimmed } }));
    if (res.ok) {
      await onDone(res.data);
      setBusy(false);
      return;
    }
    setBusy(false);
    setError(failureLines(res.failure));
  };

  return (
    <Dialog title="Decide this appeal" onClose={onClose} busy={busy} wide>
      <form class="flex flex-col gap-3" onSubmit={(e) => void submit(e)} aria-label="Decide the appeal">
        <fieldset class="flex flex-col gap-2 border border-line p-2">
          <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Outcome</legend>
          <label class="flex items-start gap-2">
            <input type="radio" name="outcome" class="mt-1" checked={outcome === 'upheld'} onChange={() => setOutcome('upheld')} />
            <span>
              <span class="font-semibold">Upheld</span>
              <span class="block text-xs text-ink-muted">The first answer stays. The citizen is told a person checked it again.</span>
            </span>
          </label>
          <label class="flex items-start gap-2">
            <input type="radio" name="outcome" class="mt-1" checked={outcome === 'overturned'} onChange={() => setOutcome('overturned')} />
            <span>
              <span class="font-semibold">Overturned</span>
              <span class="block text-xs text-ink-muted">The application becomes approved, the citizen is told, and a payment is requested at the rule amount (a second officer releases it above the limit).</span>
            </span>
          </label>
        </fieldset>
        <label class="flex flex-col gap-1">
          <span>
            Reason (required, {MIN_REASON} to {MAX_REASON} characters; stored in the audit log)
          </span>
          <textarea rows={3} maxLength={MAX_REASON} class="rounded-sm border border-line-strong bg-paper p-2 text-sm" value={reason} aria-invalid={touched && bad} onInput={(e) => setReason(e.currentTarget.value)} data-testid="appeal-decide-reason" />
        </label>
        <p class={touched && bad ? 'text-danger' : 'text-xs text-ink-subtle'} role={touched && bad ? 'alert' : undefined}>
          {touched && outcome === null ? 'Choose an outcome. ' : ''}
          {touched && trimmed.length < MIN_REASON ? `A reason of at least ${MIN_REASON} characters is required.` : `${trimmed.length} of ${MIN_REASON} characters minimum.`}
        </p>
        {error ? (
          <div role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger" data-testid="appeal-error">
            <p class="font-semibold">{error.title}</p>
            <ul class="list-disc ps-5">
              {error.lines.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
            {error.code ? <p class="font-mono text-xs">[{error.code}]</p> : null}
          </div>
        ) : null}
        <div class="flex flex-wrap gap-2">
          <button type="submit" class={outcome ? BTN_PRIMARY : BTN} disabled={busy}>
            {busy ? 'Saving…' : outcome ? `Confirm ${outcome}` : 'Confirm'}
          </button>
          <button type="button" class={BTN} onClick={onClose} disabled={busy}>
            {error ? 'Close' : 'Cancel'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
