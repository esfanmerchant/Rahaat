import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_DANGER, BTN_PRIMARY, copyText, flashFail, FlashLine, LoadMore, usePaged, type Flash } from '../kit';
import { CheckMark, CrossMark, Dialog, Empty, FailureLine, LoadView } from '../loadview';
import { Badge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

type Hook = components['schemas']['WebhookOut'];
type Created = components['schemas']['WebhookCreated'];
type Delivery = components['schemas']['DeliveryOut'];
type EventDef = components['schemas']['EventOut'];

const MOCK_URL = 'mock://receiver';
const STATUS_TONE = { pending: 'info', delivered: 'good', failed: 'warn', dead: 'bad' } as const;
const STATUSES = ['all', 'pending', 'delivered', 'failed', 'dead'] as const;

/** Calls `fn` every `ms` while the tab is visible, so a delivery visibly moves from pending to delivered. */
function useTicker(fn: () => void, ms: number): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) ref.current();
    }, ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

/** Webhooks of this department. The secret appears once; deliveries and the mock receiver show what really happened. */
export function WebhooksPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [hooks, reloadHooks] = useLoad(() => call(api.GET('/v1/admin/webhooks')), []);
  const [events, reloadEvents] = useLoad(() => call(api.GET('/v1/admin/webhooks/events')), []);
  const [sel, setSel] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ created: Created; why: string } | null>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const bump = () => setTick((n) => n + 1);

  // The first webhook is selected once the list arrives.
  useEffect(() => {
    if (hooks.state === 'ok' && (sel === null || !hooks.data.some((h) => h.id === sel))) setSel(hooks.data[0]?.id ?? null);
  }, [hooks, sel]);

  const hasMock = hooks.state === 'ok' && hooks.data.some((h) => h.url === MOCK_URL);
  const allEvents = events.state === 'ok' ? events.data.map((e) => e.name) : [];

  const demo = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/admin/webhooks', { body: { url: MOCK_URL, events: allEvents } }));
    setBusy(false);
    if (!res.ok) {
      const f = flashFail(res.failure);
      if (f && res.failure.problem?.code === 'webhook_exists') f.text = 'The demo webhook already exists. Select it in the list and press Send test.';
      return setFlash(f);
    }
    setSecret({ created: res.data, why: 'The demo webhook is ready. It points at the built-in mock receiver.' });
    setSel(res.data.id);
    reloadHooks();
    setFlash({ tone: 'ok', text: 'Demo webhook created. Press Send test to see a signed delivery arrive.' });
  };

  const selected = hooks.state === 'ok' ? hooks.data.find((h) => h.id === sel) : undefined;

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Webhooks
        </h1>
        <button type="button" class={BTN_PRIMARY} disabled={busy || hasMock || events.state !== 'ok'} onClick={() => void demo()} title={hasMock ? 'The demo webhook exists already' : 'Creates a webhook that points at the mock receiver'}>
          {busy ? 'Creating…' : 'Demo webhook'}
        </button>
        <button type="button" class={BTN} onClick={() => { reloadHooks(); bump(); }}>
          Refresh
        </button>
        <span class="text-xs text-ink-subtle">Each delivery is signed with HMAC-SHA256. Payloads carry ids and status words only, never a name, phone or ID number.</span>
      </div>
      <FlashLine flash={flash} />
      {secret ? <SecretOnce created={secret.created} why={secret.why} onDone={() => setSecret(null)} /> : null}

      <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Section id="hooks" title="Webhooks of this department">
          <LoadView state={hooks} reload={reloadHooks} what="the webhooks" rows={3}>
            {(list) =>
              list.length === 0 ? (
                <Empty title="No webhooks yet" body="Press Demo webhook to create one that points at the mock receiver, or add your own address on the right." />
              ) : (
                <div class="overflow-auto">
                  <table class="st-table w-full border-collapse text-sm">
                    <thead>
                      <tr>
                        <Th>Address</Th>
                        <Th>Events</Th>
                        <Th>State</Th>
                        <Th>Secret</Th>
                        <Th>Pending</Th>
                        <Th>Dead</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((h) => (
                        <tr key={h.id} class={sel === h.id ? 'st-cursor' : ''}>
                          <td class={TD}>
                            <button type="button" class="break-all text-start font-mono text-xs underline" aria-pressed={sel === h.id} onClick={() => setSel(h.id)}>
                              {h.url}
                            </button>
                            {h.is_mock_receiver ? <span class="ms-2 st-chip info">mock receiver</span> : null}
                          </td>
                          <td class={`${TD} text-xs`}>{h.events.length === 0 ? 'none' : h.events.length > 3 ? `${h.events.length} events` : h.events.join(', ')}</td>
                          <td class={TD}>
                            <Badge tone={h.active ? 'good' : 'neutral'}>{h.active ? 'active' : 'disabled'}</Badge>
                          </td>
                          <td class={TD}>
                            <Mono>{h.secret_hint}</Mono>
                          </td>
                          <td class={`${TD} rh-num text-end font-mono`}>{h.deliveries_pending ?? 0}</td>
                          <td class={`${TD} rh-num text-end font-mono ${(h.deliveries_dead ?? 0) > 0 ? 'text-danger' : ''}`}>{h.deliveries_dead ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </LoadView>
        </Section>

        <Section id="new" title="New webhook">
          <LoadView state={events} reload={reloadEvents} what="the event list" rows={3}>
            {(defs) => (
              <HookForm
                events={defs}
                submitLabel="Create webhook"
                onSubmit={async (url, evs) => {
                  const res = await call(api.POST('/v1/admin/webhooks', { body: { url, events: evs } }));
                  if (!res.ok) return flashFail(res.failure);
                  setSecret({ created: res.data, why: 'The webhook is created.' });
                  setSel(res.data.id);
                  reloadHooks();
                  return null;
                }}
              />
            )}
          </LoadView>
        </Section>
      </div>

      {selected ? (
        <Manage
          key={selected.id}
          hook={selected}
          events={events.state === 'ok' ? events.data : []}
          tick={tick}
          onChanged={() => { reloadHooks(); bump(); }}
          onSecret={(created, why) => setSecret({ created, why })}
          onDeleted={() => { setSel(null); reloadHooks(); }}
          onTested={bump}
        />
      ) : null}

      <ReceiverPanel hooks={hooks.state === 'ok' ? hooks.data : []} tick={tick} onRefreshed={bump} />
    </section>
  );
}

function SecretOnce({ created, why, onDone }: { created: Created; why: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div role="alert" class="st-secret p-3" data-testid="webhook-secret-once">
      <p class="font-semibold text-warning-ink">Copy the signing secret now. It is shown once; after this only its last characters are kept on screen, and it cannot be shown again.</p>
      <p class="mt-1 text-xs text-ink-muted">
        {why} <Mono>{created.url}</Mono>
      </p>
      <p class="mt-2 flex flex-wrap items-center gap-2">
        <code class="break-all border border-line-strong bg-paper px-2 py-1 font-mono text-xs" data-testid="webhook-secret">
          {created.secret}
        </code>
        <button type="button" class={BTN} onClick={() => { copyText(created.secret); setCopied(true); }}>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" class={BTN} onClick={onDone}>
          I have stored it, hide it
        </button>
      </p>
      <p class="mt-1 text-xs text-ink-subtle">Verify each delivery with HMAC-SHA256 over timestamp + "." + body, compared to the X-Rahat-Signature header.</p>
    </div>
  );
}

function EventPicker({ defs, picked, onChange }: { defs: EventDef[]; picked: string[]; onChange: (next: string[]) => void }) {
  const all = defs.length > 0 && defs.every((d) => picked.includes(d.name));
  return (
    <fieldset class="flex flex-col gap-1 border border-line p-2">
      <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Events</legend>
      <label class="flex items-center gap-2 text-xs text-ink-muted">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.currentTarget.checked ? defs.map((d) => d.name) : [])} />
        All events
      </label>
      <div class="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
        {defs.map((d) => (
          <label key={d.name} class="flex items-start gap-2">
            <input
              type="checkbox"
              class="mt-1"
              checked={picked.includes(d.name)}
              onChange={(e) => onChange(e.currentTarget.checked ? [...picked, d.name] : picked.filter((x) => x !== d.name))}
            />
            <span>
              <span class="font-mono text-xs">{d.name}</span>
              <span class="block text-xs leading-snug text-ink-muted">{d.description}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function HookForm({
  events,
  initialUrl = '',
  initialEvents = [],
  submitLabel,
  onSubmit,
  onCancel,
}: {
  events: EventDef[];
  initialUrl?: string;
  initialEvents?: string[];
  submitLabel: string;
  onSubmit: (url: string, events: string[]) => Promise<Flash>;
  onCancel?: () => void;
}) {
  const [url, setUrl] = useState(initialUrl);
  const [picked, setPicked] = useState<string[]>(initialEvents);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const valid = url.trim().length >= 8 && picked.length > 0;
  return (
    <form
      class="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || busy) return;
        setBusy(true);
        setFlash(null);
        void onSubmit(url.trim(), picked).then((f) => {
          setBusy(false);
          setFlash(f);
          if (f === null && initialUrl === '') {
            setUrl('');
            setPicked([]);
          }
        });
      }}
    >
      <label class="flex flex-col gap-1">
        Address (https, or {MOCK_URL} for the built-in receiver)
        <input class={`${INPUT} font-mono`} value={url} maxLength={500} autoComplete="off" spellcheck={false} placeholder="https://partner.example/hooks/rahat" onInput={(e) => setUrl(e.currentTarget.value)} />
      </label>
      <EventPicker defs={events} picked={picked} onChange={setPicked} />
      <p class="text-xs text-ink-subtle">The server refuses private, loopback and link-local addresses (SSRF checks run again at every send).</p>
      <div class="flex flex-wrap gap-2">
        <button type="submit" class={BTN_PRIMARY} disabled={!valid || busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
        {onCancel ? (
          <button type="button" class={BTN} onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
      <FlashLine flash={flash} />
    </form>
  );
}

function Manage({
  hook,
  events,
  tick,
  onChanged,
  onSecret,
  onDeleted,
  onTested,
}: {
  hook: Hook;
  events: EventDef[];
  tick: number;
  onChanged: () => void;
  onSecret: (c: Created, why: string) => void;
  onDeleted: () => void;
  onTested: () => void;
}) {
  const [dialog, setDialog] = useState<'edit' | 'rotate' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const [status, setStatus] = useState<(typeof STATUSES)[number]>('all');
  const list = usePaged<Delivery>(
    (cursor) =>
      call(
        api.GET('/v1/admin/webhooks/{webhook_id}/deliveries', {
          params: { path: { webhook_id: hook.id }, query: { limit: 25, ...(status !== 'all' ? { status } : {}), ...(cursor ? { cursor: String(cursor) } : {}) } },
        }),
      ),
    [hook.id, status],
  );
  useEffect(() => {
    if (tick > 0) list.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);
  useTicker(list.reload, 5000);

  const afterAction = () => {
    // The worker sends a moment later: look again a few times so the row moves from pending to delivered.
    for (const ms of [700, 2200, 5000]) window.setTimeout(() => { list.reload(); onTested(); }, ms);
  };

  const test = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/admin/webhooks/{webhook_id}/test', { params: { path: { webhook_id: hook.id } } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: `Test event queued (delivery ${res.data.id.slice(0, 8)}). Watch the table below.` });
    list.reload();
    afterAction();
  };
  const toggle = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.PATCH('/v1/admin/webhooks/{webhook_id}', { params: { path: { webhook_id: hook.id } }, body: { active: !hook.active } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: hook.active ? 'Disabled. No new deliveries are queued for it.' : 'Enabled.' });
    onChanged();
  };
  const redeliver = async (d: Delivery) => {
    setFlash(null);
    const res = await call(api.POST('/v1/admin/webhooks/{webhook_id}/deliveries/{delivery_id}/redeliver', { params: { path: { webhook_id: hook.id, delivery_id: d.id } } }));
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: `Queued a new delivery of ${d.event} (${res.data.id.slice(0, 8)}).` });
    list.reload();
    afterAction();
  };

  return (
    <Section
      id="manage"
      title={`Deliveries for ${hook.url}`}
      aside={
        <span class="flex items-center gap-1">
          <Badge tone={hook.active ? 'good' : 'neutral'}>{hook.active ? 'active' : 'disabled'}</Badge>
        </span>
      }
    >
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-2">
          <button type="button" class={BTN_PRIMARY} disabled={busy || !hook.active} onClick={() => void test()} title={hook.active ? '' : 'Enable the webhook first'}>
            Send test
          </button>
          <button type="button" class={BTN} disabled={busy} onClick={() => setDialog('edit')}>
            Edit
          </button>
          <button type="button" class={BTN} disabled={busy} onClick={() => void toggle()}>
            {hook.active ? 'Disable' : 'Enable'}
          </button>
          <button type="button" class={BTN} disabled={busy} onClick={() => setDialog('rotate')}>
            Rotate secret
          </button>
          <button type="button" class={BTN_DANGER} disabled={busy} onClick={() => setDialog('delete')}>
            Delete
          </button>
          <span class="mx-2 h-5 border-s border-line" aria-hidden="true" />
          <label class="flex items-center gap-1">
            Status
            <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value as (typeof STATUSES)[number])}>
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
        </div>
        <FlashLine flash={flash} />
        <p class="text-xs text-ink-subtle">
          Subscribed to: {hook.events.length ? hook.events.join(', ') : 'nothing'}. A failed delivery retries with growing waits and ends as dead after the last attempt; a dead one can be redelivered by hand.
        </p>

        {list.status === 'loading' ? (
          <div role="status" aria-label="Loading deliveries" class="flex flex-col gap-2">
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
            <div class="rh-skeleton h-7" />
          </div>
        ) : null}
        {list.status === 'fail' && list.failure ? <FailureLine failure={list.failure} what="the deliveries" reload={list.reload} /> : null}
        {list.status === 'ok' && list.items.length === 0 ? <Empty title="No deliveries" body={status === 'all' ? 'Nothing has been queued for this webhook yet. Press Send test.' : `No ${status} deliveries.`} /> : null}
        {list.status === 'ok' && list.items.length > 0 ? (
          <div class="overflow-auto">
            <table class="st-table w-full border-collapse text-sm" data-testid="deliveries">
              <thead>
                <tr>
                  <Th>Event</Th>
                  <Th>Status</Th>
                  <Th>Attempts</Th>
                  <Th>Response</Th>
                  <Th>Last error</Th>
                  <Th>Next attempt</Th>
                  <Th>Created</Th>
                  <Th>Action</Th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((d, i) => (
                  <DeliveryRow key={d.id} d={d} i={i} onRedeliver={() => void redeliver(d)} />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
      </div>

      {dialog === 'edit' ? (
        <Dialog title="Edit webhook" onClose={() => setDialog(null)} wide>
          <HookForm
            events={events}
            initialUrl={hook.url}
            initialEvents={hook.events}
            submitLabel="Save changes"
            onCancel={() => setDialog(null)}
            onSubmit={async (url, evs) => {
              const res = await call(api.PATCH('/v1/admin/webhooks/{webhook_id}', { params: { path: { webhook_id: hook.id } }, body: { url, events: evs } }));
              if (!res.ok) return flashFail(res.failure);
              setDialog(null);
              onChanged();
              return null;
            }}
          />
        </Dialog>
      ) : null}
      {dialog === 'rotate' ? (
        <ConfirmDialog
          title="Rotate the signing secret?"
          body="A new secret is created and shown once. The old one stops working at once, so the receiver must be updated before the next delivery verifies."
          label="Rotate secret"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const res = await call(api.POST('/v1/admin/webhooks/{webhook_id}/rotate-secret', { params: { path: { webhook_id: hook.id } } }));
            if (!res.ok) return flashFail(res.failure);
            setDialog(null);
            onSecret(res.data, 'The secret was rotated.');
            onChanged();
            return null;
          }}
        />
      ) : null}
      {dialog === 'delete' ? (
        <ConfirmDialog
          title="Delete this webhook?"
          body="The webhook and its delivery log are deleted. This cannot be undone."
          label="Delete webhook"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const res = await call(api.DELETE('/v1/admin/webhooks/{webhook_id}', { params: { path: { webhook_id: hook.id } } }));
            if (!res.ok) return flashFail(res.failure);
            setDialog(null);
            onDeleted();
            return null;
          }}
        />
      ) : null}
    </Section>
  );
}

function ConfirmDialog({ title, body, label, danger, onClose, onConfirm }: { title: string; body: string; label: string; danger?: boolean; onClose: () => void; onConfirm: () => Promise<Flash> }) {
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  return (
    <Dialog title={title} onClose={onClose} busy={busy}>
      <p>{body}</p>
      <FlashLine flash={flash} />
      <div class="flex gap-2">
        <button
          type="button"
          class={danger ? BTN_DANGER : BTN_PRIMARY}
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void onConfirm().then((f) => {
              setBusy(false);
              setFlash(f);
            });
          }}
        >
          {busy ? 'Working…' : label}
        </button>
        <button type="button" class={BTN} onClick={onClose} disabled={busy}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

function DeliveryRow({ d, i, onRedeliver }: { d: Delivery; i: number; onRedeliver: () => void }) {
  const [open, setOpen] = useState(false);
  const left = d.max_attempts - d.attempts;
  return (
    <>
      <tr class="st-row-in" style={{ '--i': i }}>
        <td class={TD}>
          <button type="button" class="text-start font-mono text-xs underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {d.event}
          </button>
          <span class="block font-mono text-xs text-ink-subtle">{d.id.slice(0, 8)}</span>
        </td>
        <td class={TD}>
          <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>
        </td>
        <td class={`${TD} rh-num font-mono`} title={`${left} attempt(s) left`}>
          {d.attempts} / {d.max_attempts}
        </td>
        <td class={`${TD} rh-num font-mono`}>{d.response_code ?? <span class="text-ink-subtle">none</span>}</td>
        <td class={`${TD} max-w-64 break-words text-xs`}>{d.last_error ? humanize(d.last_error) : <span class="text-ink-subtle">none</span>}</td>
        <td class={`${TD} font-mono text-xs`}>{d.status === 'delivered' ? 'done' : d.status === 'dead' ? 'no more attempts' : d.next_attempt_at ? fmtTime(d.next_attempt_at) : 'queued'}</td>
        <td class={`${TD} font-mono text-xs`}>{fmtTime(d.created_at)}</td>
        <td class={TD}>
          <button type="button" class={BTN} onClick={onRedeliver} title="Queues a new delivery of the same event">
            Redeliver
          </button>
        </td>
      </tr>
      {open ? (
        <tr>
          <td class={TD} colSpan={8}>
            <pre class="st-code" tabIndex={0} aria-label={`Payload of delivery ${d.id}`}>
              {JSON.stringify(d.payload, null, 2)}
            </pre>
          </td>
        </tr>
      ) : null}
    </>
  );
}

type Received = {
  received_at?: string;
  webhook_id?: string;
  delivery_id?: string;
  event?: string;
  signature_valid?: boolean;
  duplicate?: boolean;
  answered?: number;
  body?: unknown;
};

/** What the built-in mock receiver got, with a drawn check for a verified signature and a cross for one that failed. */
function ReceiverPanel({ hooks, tick, onRefreshed }: { hooks: Hook[]; tick: number; onRefreshed: () => void }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/admin/webhooks/mock-receiver/received', { params: { query: { limit: 30 } } })), []);
  useEffect(() => {
    if (tick > 0) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);
  useTicker(reload, 5000);
  const mock = hooks.find((h) => h.url === MOCK_URL);
  return (
    <Section
      id="receiver"
      title="Mock receiver"
      aside={
        <button type="button" class={BTN} onClick={() => { reload(); onRefreshed(); }}>
          Refresh
        </button>
      }
    >
      <LoadView state={loaded} reload={reload} what="the mock receiver" rows={3}>
        {(data) => {
          const items = (data.items ?? []) as Received[];
          if (data.reachable === false) return <p class="text-ink-muted">The mock receiver is not reachable in this deployment. Deliveries to {MOCK_URL} will fail and retry.</p>;
          if (items.length === 0) {
            return (
              <Empty title="Nothing has arrived yet" body={mock ? 'Select the demo webhook and press Send test. The receiver checks the signature and lists the delivery here.' : 'Create the demo webhook, then press Send test.'} />
            );
          }
          return (
            <div class="overflow-auto">
              <table class="st-table w-full border-collapse text-sm" data-testid="receiver">
                <thead>
                  <tr>
                    <Th>Received</Th>
                    <Th>Event</Th>
                    <Th>Signature</Th>
                    <Th>Answered</Th>
                    <Th>Delivery</Th>
                    <Th>Body</Th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((r, i) => (
                    <ReceivedRow key={`${r.delivery_id}-${r.received_at}-${i}`} r={r} i={i} />
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </LoadView>
    </Section>
  );
}

function ReceivedRow({ r, i }: { r: Received; i: number }) {
  const [open, setOpen] = useState(false);
  const ok = r.signature_valid === true;
  return (
    <>
      <tr class="st-row-in" style={{ '--i': i }}>
        <td class={`${TD} font-mono text-xs`}>{r.received_at ? fmtTime(r.received_at) : 'n/a'}</td>
        <td class={`${TD} font-mono text-xs`}>{r.event || 'n/a'}</td>
        <td class={TD}>
          <span class={`inline-flex items-center gap-1 font-semibold ${ok ? 'text-primary-strong' : 'text-danger'}`}>
            {ok ? <CheckMark label="signature valid" /> : <CrossMark label="signature not valid" />}
            {ok ? 'valid' : 'not valid'}
          </span>
          {r.duplicate ? <span class="ms-2 st-chip warn">duplicate</span> : null}
        </td>
        <td class={`${TD} rh-num font-mono`}>{r.answered ?? 'n/a'}</td>
        <td class={TD}>
          <Mono>{(r.delivery_id ?? '').slice(0, 8) || 'n/a'}</Mono>
        </td>
        <td class={TD}>
          {r.body ? (
            <button type="button" class="underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              {open ? 'Hide' : 'Show'}
            </button>
          ) : (
            <span class="text-ink-subtle">none kept</span>
          )}
        </td>
      </tr>
      {open ? (
        <tr>
          <td class={TD} colSpan={6}>
            <pre class="st-code" tabIndex={0} aria-label="Body the receiver got">
              {JSON.stringify(r.body, null, 2)}
            </pre>
          </td>
        </tr>
      ) : null}
    </>
  );
}
