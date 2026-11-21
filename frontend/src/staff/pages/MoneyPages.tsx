import { useEffect, useMemo, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_DANGER, BTN_PRIMARY, flashFail, FlashLine, LoadMore, ReasonAction, usePaged, type Flash } from '../kit';
import { Badge, fmtTime, humanize, INPUT, Mono, TD, Th } from '../ui';

type S = components['schemas'];
type Payment = S['PaymentOut'];
type Approval = S['app__contracts__api__ApprovalOut'];
type PaymentStatus = NonNullable<NonNullable<components['schemas']['PaymentOut']>['status']>;

const PAYMENT_STATUSES = ['pending_approval', 'approved', 'submitted', 'settled', 'failed', 'reversed', 'cancelled'] as const;
const APPROVAL_STATUSES = ['pending', 'approved', 'rejected', 'expired'] as const;
const rs = (n: number) => `Rs ${n.toLocaleString('en-US')}`;
const short = (id: string | null | undefined) => (id ? id.slice(0, 8) : 'n/a');
const payTone = (s: PaymentStatus) => (s === 'settled' ? 'good' : s === 'failed' || s === 'reversed' || s === 'cancelled' ? 'bad' : s === 'pending_approval' ? 'warn' : 'neutral');

/** Payment amounts by payment id and people by application id, best effort: the table still works without them. */
function useLookups() {
  const [payments, setPayments] = useState<Map<string, Payment>>(new Map());
  const [people, setPeople] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    void call(api.GET('/v1/payments', { params: { query: { limit: 100 } } })).then((r) => r.ok && setPayments(new Map(r.data.items.map((p) => [p.id, p]))));
    void call(api.GET('/v1/cases', { params: { query: { status: 'all', limit: 100 } } })).then(
      (r) => r.ok && setPeople(new Map(r.data.items.flatMap((c) => (c.application_id && c.subject_name ? [[c.application_id, c.subject_name] as [string, string]] : [])))),
    );
  }, []);
  return { payments, people };
}

/** Payments above the department's limit wait here for a second officer (maker-checker). */
export function ApprovalsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const me = session.value.status === 'signed-in' ? session.value.user.id : '';
  const [status, setStatus] = useState<(typeof APPROVAL_STATUSES)[number]>('pending');
  const [open, setOpen] = useState<{ id: string; approve: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const { payments, people } = useLookups();
  const list = usePaged<Approval>((cursor) => call(api.GET('/v1/approvals', { params: { query: { status, limit: 25, ...(cursor ? { cursor: String(cursor) } : {}) } } })), [status]);

  const decide = async (a: Approval, approve: boolean, reason: string) => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/approvals/{approval_id}/decide', { params: { path: { approval_id: a.id } }, body: { approve, reason } }));
    setBusy(false);
    if (res.ok) {
      setOpen(null);
      setFlash({ tone: 'ok', text: approve ? 'Approved. The payment is released.' : 'Refused. The payment is stopped.' });
      list.reload();
    } else {
      const f = flashFail(res.failure);
      if (f && (res.failure.kind === 'forbidden' || f.code === 'four_eyes_required')) f.text = `Refused by the server: the officer who requested this cannot also decide it. Ask a different officer. (${f.text})`;
      setFlash(f);
    }
  };

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Payment approvals
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value as typeof status)}>
            {APPROVAL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button type="button" class={BTN} onClick={list.reload}>
          Refresh
        </button>
        <span class="ms-auto text-xs text-ink-subtle">Payments above the department limit need a second officer. The server refuses the officer who approved the case.</span>
      </div>
      <FlashLine flash={flash} />
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading approvals…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title={`No ${status} approvals`} body="Nothing is waiting for a second officer." /> : null}
      {list.items.length > 0 ? (
        <div class="overflow-x-auto border border-line">
          <table class="w-full border-collapse text-sm">
            <caption class="sr-only">Payment approvals, oldest first</caption>
            <thead>
              <tr>
                <Th>Amount</Th>
                <Th>Person</Th>
                <Th>Case approved by</Th>
                <Th>Waiting since</Th>
                <Th>Status</Th>
                <Th>Decision</Th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((a) => {
                const pay = payments.get(a.subject_id);
                const person = pay ? people.get(pay.application_id) : undefined;
                const mine = !!me && a.requested_by === me;
                return (
                  <>
                    <tr key={a.id} class="hover:bg-sunken">
                      <td class={`${TD} font-mono tabular-nums`}>{pay ? rs(pay.amount_pkr) : 'n/a'}</td>
                      <td class={TD}>{person ?? (pay ? <Mono title="application id">{short(pay.application_id)}</Mono> : 'n/a')}</td>
                      <td class={TD}>
                        <Mono>{short(a.requested_by)}</Mono> {mine ? <Badge tone="info">you</Badge> : null}
                      </td>
                      <td class={`${TD} font-mono text-xs`}>{fmtTime(a.created_at)}</td>
                      <td class={TD}>
                        <Badge tone={a.status === 'pending' ? 'warn' : a.status === 'approved' ? 'good' : 'neutral'}>{a.status}</Badge>
                        {a.reason ? <div class="max-w-xs text-xs text-ink-muted">{a.reason}</div> : null}
                      </td>
                      <td class={TD}>
                        {a.status === 'pending' ? (
                          <span class="flex gap-2">
                            <button type="button" class={BTN_PRIMARY} onClick={() => setOpen({ id: a.id, approve: true })}>
                              Approve
                            </button>
                            <button type="button" class={BTN_DANGER} onClick={() => setOpen({ id: a.id, approve: false })}>
                              Refuse
                            </button>
                          </span>
                        ) : (
                          <span class="text-ink-subtle">decided by {short(a.approver_id)}</span>
                        )}
                      </td>
                    </tr>
                    {open?.id === a.id ? (
                      <tr key={`${a.id}-reason`}>
                        <td colSpan={6} class={`${TD} bg-sunken`}>
                          <ReasonAction
                            label={open.approve ? 'Approve payment' : 'Refuse payment'}
                            tone={open.approve ? 'primary' : 'danger'}
                            busy={busy}
                            help={open.approve ? 'Releases the payment. Stored in the audit log.' : 'Stops the payment. Stored in the audit log.'}
                            onSubmit={(r) => void decide(a, open.approve, r)}
                            onCancel={() => setOpen(null)}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
    </section>
  );
}

/** Every payment of the department, newest first, with the rail reference once it is submitted. */
export function PaymentsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [status, setStatus] = useState('');
  const { people } = useLookups();
  const list = usePaged<Payment>((cursor) => call(api.GET('/v1/payments', { params: { query: { limit: 25, ...(status ? { status: status as (typeof PAYMENT_STATUSES)[number] } : {}), ...(cursor ? { cursor: String(cursor) } : {}) } } })), [status]);
  const total = useMemo(() => list.items.reduce((sum, p) => sum + p.amount_pkr, 0), [list.items]);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Payments
        </h1>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value)}>
            <option value="">All</option>
            {PAYMENT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" class={BTN} onClick={list.reload}>
          Refresh
        </button>
        <span class="ms-auto text-xs text-ink-subtle">
          {list.items.length} shown, {rs(total)} in total. Simulated payment rail: no real money moves.
        </span>
      </div>
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading payments…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No payments" body={status ? 'No payment has this status.' : 'No payment has been created yet.'} /> : null}
      {list.items.length > 0 ? (
        <div class="overflow-x-auto border border-line">
          <table class="w-full border-collapse text-sm">
            <caption class="sr-only">Payments, newest first</caption>
            <thead>
              <tr>
                <Th>Created</Th>
                <Th>Person</Th>
                <Th>Amount</Th>
                <Th>Status</Th>
                <Th>Rail reference</Th>
                <Th>Approval</Th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((p) => (
                <tr key={p.id} class="hover:bg-sunken">
                  <td class={`${TD} font-mono text-xs`}>{fmtTime(p.created_at)}</td>
                  <td class={TD}>{people.get(p.application_id) ?? <Mono>{short(p.application_id)}</Mono>}</td>
                  <td class={`${TD} font-mono tabular-nums`}>{rs(p.amount_pkr)}</td>
                  <td class={TD}>
                    <Badge tone={payTone(p.status as PaymentStatus)}>{humanize(p.status)}</Badge>
                  </td>
                  <td class={TD}>{p.rail_ref ? <Mono>{p.rail_ref}</Mono> : <span class="text-ink-subtle">none yet</span>}</td>
                  <td class={TD}>{p.approval_id ? <Mono>{short(p.approval_id)}</Mono> : <span class="text-ink-subtle">not needed</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
    </section>
  );
}
