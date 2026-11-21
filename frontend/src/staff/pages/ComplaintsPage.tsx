import { useMemo, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, failureText, LoadMore, usePaged } from '../kit';
import { CheckMark, Dialog, Empty, FailureLine } from '../loadview';
import { Badge, fmtAge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useNow } from '../ui';
import { HeatBar } from '../viz';

type Row = components['schemas']['ComplaintStaffOut'];

const STATUSES = ['active', 'resolved', 'all'] as const;
type StatusFilter = (typeof STATUSES)[number];
const MIN_REASON = 5;
const MAX_REASON = 1000;
const CATEGORY: Record<Row['category'], string> = { service: 'Service', staff: 'About staff', scam_attempt: 'Scam attempt', payment: 'Payment', other: 'Other' };

/** Complaints from citizens. A complaint is a case; a scam report is routed to the scam queue with higher priority. */
export function ComplaintsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = session.value.status === 'signed-in' ? session.value.active.role : '';
  const now = useNow();
  const [status, setStatus] = useState<StatusFilter>('active');
  const [sel, setSel] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const list = usePaged<Row>((cursor) => call(api.GET('/v1/complaints', { params: { query: { status, limit: 50, ...(cursor ? { cursor: String(cursor) } : {}) } } })), [status]);
  // Most urgent first (priority 0 is the most urgent), then oldest.
  const rows = useMemo(() => [...list.items].sort((a, b) => a.priority - b.priority || a.created_at.localeCompare(b.created_at)), [list.items]);
  const selected = rows.find((r) => r.id === sel) ?? null;

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Complaints
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value as StatusFilter)}>
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
        <span class="text-xs text-ink-subtle">Most urgent first. Details are shown only where the citizen's consent allows staff to read them.</span>
      </div>
      {flash ? (
        <p role="status" class="flex items-center gap-1 border border-primary bg-primary-soft px-3 py-2 text-primary-strong">
          <CheckMark />
          {flash}
        </p>
      ) : null}

      <Section id="complaints" title={`${status === 'all' ? 'All' : humanize(status)} complaints`} aside={<span class="font-mono text-xs text-ink-subtle">{rows.length} shown</span>}>
        {list.status === 'loading' ? (
          <div role="status" aria-label="Loading complaints" class="flex flex-col gap-2">
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
          </div>
        ) : null}
        {list.status === 'fail' && list.failure ? <FailureLine failure={list.failure} what="the complaints" reload={list.reload} /> : null}
        {list.status === 'ok' && rows.length === 0 ? <Empty title={status === 'active' ? 'No complaints waiting' : 'No complaints here'} body={status === 'active' ? 'Complaints a citizen files appear here as cases.' : 'Nothing matches this status.'} /> : null}
        {list.status === 'ok' && rows.length > 0 ? (
          <div class="overflow-auto">
            <table class="st-table w-full border-collapse text-sm" data-testid="complaints">
              <thead>
                <tr>
                  <Th>Priority</Th>
                  <Th>Category</Th>
                  <Th>Queue</Th>
                  <Th>Status</Th>
                  <Th>Age</Th>
                  <Th>Details</Th>
                  <Th>Action</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const minutes = Math.max(0, Math.floor((now - new Date(r.created_at).getTime()) / 60000));
                  const isOpen = r.resolved_at === null || r.resolved_at === undefined;
                  return (
                    <tr key={r.id} class={`st-row-in ${sel === r.id ? 'st-cursor' : ''}`} style={{ '--i': i }}>
                      <td class={TD}>
                        <HeatBar priority={r.priority} />
                      </td>
                      <td class={TD}>
                        <Badge tone={r.category === 'scam_attempt' ? 'bad' : 'neutral'}>{CATEGORY[r.category]}</Badge>
                      </td>
                      <td class={`${TD} text-xs`}>{r.case_kind === 'scam_review' ? 'scam queue' : 'complaints'}</td>
                      <td class={TD}>
                        <Badge tone={isOpen ? 'warn' : 'good'}>{humanize(r.status)}</Badge>
                      </td>
                      <td class={`${TD} font-mono text-xs`} title={fmtTime(r.created_at)}>
                        {fmtAge(minutes)}
                      </td>
                      <td class={`${TD} max-w-96 text-xs`}>
                        {r.details ? (
                          <span class="whitespace-pre-wrap break-words">{r.details}</span>
                        ) : (
                          <span class="text-ink-subtle" title="The citizen wrote nothing, or their consent does not allow staff to read it. The server decides.">
                            hidden or not given
                          </span>
                        )}
                      </td>
                      <td class={TD}>
                        {isOpen && role === 'officer' ? (
                          <button type="button" class={BTN} onClick={() => setSel(r.id)} data-testid="complaint-resolve-open">
                            Resolve
                          </button>
                        ) : r.resolution ? (
                          <span class="text-xs text-ink-muted">{r.resolution}</span>
                        ) : (
                          <Mono>{r.id.slice(0, 8)}</Mono>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
      </Section>

      {selected ? (
        <ResolveDialog
          row={selected}
          onClose={() => setSel(null)}
          onDone={(text) => {
            setSel(null);
            setFlash(text);
            list.reload();
          }}
        />
      ) : null}
    </section>
  );
}

function ResolveDialog({ row, onClose, onDone }: { row: Row; onClose: () => void; onDone: (text: string) => void }) {
  const [outcome, setOutcome] = useState<'resolved' | 'dismissed' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = reason.trim();
  const bad = outcome === null || trimmed.length < MIN_REASON || trimmed.length > MAX_REASON;

  const submit = async (e: Event) => {
    e.preventDefault();
    setTouched(true);
    if (bad || busy || outcome === null) return;
    setBusy(true);
    setError(null);
    const res = await call(api.POST('/v1/complaints/{case_id}/resolve', { params: { path: { case_id: row.id } }, body: { outcome, reason: trimmed } }));
    setBusy(false);
    if (res.ok) return onDone(`Complaint ${outcome}. The citizen is told in plain words; your reason stays in the audit log.`);
    const code = res.failure.problem?.code;
    setError(
      res.failure.kind === 'forbidden'
        ? `The server refused this${code === 'consent_required' ? ': the citizen has withdrawn consent, so staff may not act on their file.' : '. Only an officer can resolve a complaint.'} ${res.failure.problem?.detail ?? ''}`
        : failureText(res.failure),
    );
  };

  return (
    <Dialog title="Resolve this complaint" onClose={onClose} busy={busy} wide>
      <form class="flex flex-col gap-3" onSubmit={(e) => void submit(e)} aria-label="Resolve the complaint">
        <p class="border border-line bg-sunken px-3 py-2">
          <Badge tone={row.category === 'scam_attempt' ? 'bad' : 'neutral'}>{CATEGORY[row.category]}</Badge>{' '}
          <span class="whitespace-pre-wrap break-words">{row.details ?? 'No details are shown for this complaint.'}</span>
        </p>
        <fieldset class="flex flex-col gap-2 border border-line p-2">
          <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Outcome</legend>
          <label class="flex items-start gap-2">
            <input type="radio" name="c-outcome" class="mt-1" checked={outcome === 'resolved'} onChange={() => setOutcome('resolved')} />
            <span>
              <span class="font-semibold">Resolved</span>
              <span class="block text-xs text-ink-muted">The problem was looked into and dealt with.</span>
            </span>
          </label>
          <label class="flex items-start gap-2">
            <input type="radio" name="c-outcome" class="mt-1" checked={outcome === 'dismissed'} onChange={() => setOutcome('dismissed')} />
            <span>
              <span class="font-semibold">Dismissed</span>
              <span class="block text-xs text-ink-muted">Nothing to act on. The citizen is told the complaint is closed.</span>
            </span>
          </label>
        </fieldset>
        <label class="flex flex-col gap-1">
          <span>
            Reason (required, {MIN_REASON} to {MAX_REASON} characters; stored in the audit log)
          </span>
          <textarea rows={3} maxLength={MAX_REASON} class="rounded-sm border border-line-strong bg-paper p-2 text-sm" value={reason} aria-invalid={touched && bad} onInput={(e) => setReason(e.currentTarget.value)} data-testid="complaint-reason" />
        </label>
        <p class={touched && bad ? 'text-danger' : 'text-xs text-ink-subtle'} role={touched && bad ? 'alert' : undefined}>
          {touched && outcome === null ? 'Choose an outcome. ' : ''}
          {touched && trimmed.length < MIN_REASON ? `A reason of at least ${MIN_REASON} characters is required.` : `${trimmed.length} of ${MIN_REASON} characters minimum.`}
        </p>
        {error ? (
          <p role="alert" class="border border-danger bg-danger-soft px-2 py-1 text-danger">
            {error}
          </p>
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
