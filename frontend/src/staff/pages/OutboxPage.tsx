import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, copyText, flashFail, FlashLine, LoadMore, usePaged, type Flash } from '../kit';
import { Badge, fmtTime, humanize, INPUT, Mono, TD, Th } from '../ui';

type Item = components['schemas']['OutboxItem'];
type Status = 'queued' | 'sent' | 'failed' | 'read';
type Channel = 'in_app' | 'sms';

/**
 * Every message the department sent. Destinations arrive masked from the API. Message text is shown
 * as text only. The verify code is what a citizen types into the scam checker.
 */
export function OutboxPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [status, setStatus] = useState<'' | Status>('');
  const [channel, setChannel] = useState<'' | Channel>('');
  const list = usePaged<Item>(
    (cursor) => call(api.GET('/v1/outbox', { params: { query: { limit: 25, ...(status ? { status } : {}), ...(channel ? { channel } : {}), ...(cursor ? { cursor: String(cursor) } : {}) } } })),
    [status, channel],
  );
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Message outbox
        </h1>
        <label class="flex items-center gap-1">
          Channel
          <select class={INPUT} value={channel} onChange={(e) => setChannel(e.currentTarget.value as '' | Channel)}>
            <option value="">All</option>
            <option value="sms">SMS</option>
            <option value="in_app">In app</option>
          </select>
        </label>
        <label class="flex items-center gap-1">
          Status
          <select class={INPUT} value={status} onChange={(e) => setStatus(e.currentTarget.value as '' | Status)}>
            <option value="">All</option>
            {(['queued', 'sent', 'failed', 'read'] as const).map((s) => (
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
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the outbox…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No messages" body="Nothing matches. Messages appear here when the platform tells a citizen something." /> : null}
      {list.items.length > 0 ? (
        <div class="overflow-x-auto border border-line">
          <table class="w-full border-collapse text-sm">
            <caption class="sr-only">Messages sent by this department, newest first</caption>
            <thead>
              <tr>
                <Th>Created</Th>
                <Th>Channel</Th>
                <Th>Template</Th>
                <Th>Lang</Th>
                <Th>To (masked)</Th>
                <Th>Status</Th>
                <Th>Verify code</Th>
                <Th>Message</Th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((m) => (
                <tr key={m.id} class="hover:bg-sunken">
                  <td class={`${TD} font-mono text-xs`}>{fmtTime(m.created_at)}</td>
                  <td class={TD}>{m.channel}</td>
                  <td class={TD}>{humanize(m.template)}</td>
                  <td class={TD}>{m.lang}</td>
                  <td class={TD}>
                    <Mono>{m.destination ?? 'n/a'}</Mono>
                  </td>
                  <td class={TD}>
                    <Badge tone={m.status === 'failed' ? 'bad' : m.status === 'queued' ? 'warn' : 'good'}>{m.status}</Badge>
                    {m.attempts > 1 ? <span class="ms-1 text-xs text-ink-subtle">{m.attempts} tries</span> : null}
                    {m.last_error ? <div class="max-w-48 text-xs text-danger">{m.last_error}</div> : null}
                  </td>
                  <td class={TD}>
                    {m.verify_code ? (
                      <button type="button" class="font-mono font-semibold underline" title="Copy the code" onClick={() => copyText(m.verify_code ?? '')}>
                        {m.verify_code}
                      </button>
                    ) : (
                      <span class="text-ink-subtle">none</span>
                    )}
                  </td>
                  <td class={`${TD} max-w-md whitespace-pre-wrap`} dir="auto" lang={m.lang}>
                    {m.body}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
      <VerifyBox />
    </section>
  );
}

/** The public check a citizen's scam checker uses: is this code on a message Rahat really sent? */
function VerifyBox() {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const check = async () => {
    setBusy(true);
    const res = await call(api.POST('/v1/notifications/verify', { body: { code: code.trim() } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    const d = res.data;
    setFlash(
      d.genuine
        ? { tone: 'ok', text: `Genuine: ${humanize(d.template ?? 'message')} by ${d.channel ?? 'unknown channel'}${d.department ? `, ${d.department}` : ''}${d.sent_at ? `, sent ${fmtTime(d.sent_at)}` : ''}.` }
        : { tone: 'err', text: 'Not found: Rahat did not send a message with this code.' },
    );
  };
  return (
    <form
      class="flex flex-wrap items-center gap-2 border border-line p-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (code.trim().length >= 4) void check();
      }}
    >
      <label class="flex items-center gap-2">
        Check a verify code
        <input class={`${INPUT} w-40 font-mono`} value={code} maxLength={16} onInput={(e) => setCode(e.currentTarget.value)} />
      </label>
      <button type="submit" class={BTN} disabled={busy || code.trim().length < 4}>
        Check
      </button>
      <div class="basis-full empty:hidden">
        <FlashLine flash={flash} />
      </div>
    </form>
  );
}
