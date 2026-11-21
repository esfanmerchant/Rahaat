import { formatPhone } from '../phone';
import { useEffect, useMemo, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_DANGER, BTN_PRIMARY, flashFail, FlashLine, LoadMore, MIN_REASON, ReasonAction, usePaged, type Flash } from '../kit';
import { Badge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

type S = components['schemas'];
type Job = S['JobOut'];
type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'dead' | 'cancelled';
type Service = 'identity' | 'registry' | 'payment' | 'sms';

const JOB_STATUSES: JobStatus[] = ['queued', 'running', 'done', 'failed', 'dead', 'cancelled'];
const jobTone = (s: string) => (s === 'done' ? 'good' : s === 'dead' || s === 'failed' ? 'bad' : s === 'running' ? 'info' : 'neutral');

/** Background jobs of the department. A dead job can be given a fresh set of attempts, with a reason. */
export function JobsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [status, setStatus] = useState<'' | JobStatus>('');
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [retrying, setRetrying] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const list = usePaged<Job>(
    async (cursor) => {
      const res = await call(api.GET('/v1/admin/jobs', { params: { query: { limit: 25, ...(status ? { status } : {}), ...(cursor ? { cursor: String(cursor) } : {}) } } }));
      if (res.ok) setCounts(res.data.counts ?? {});
      return res;
    },
    [status],
  );

  const retry = async (job: Job, reason: string) => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/admin/jobs/{job_id}/retry', { params: { path: { job_id: job.id } }, body: { reason } }));
    setBusy(false);
    if (res.ok) {
      setRetrying('');
      setFlash({ tone: 'ok', text: `Job ${job.kind} is queued again.` });
      list.reload();
    } else setFlash(flashFail(res.failure));
  };

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Background jobs
        </h1>
        <button type="button" class={BTN} onClick={list.reload}>
          Refresh
        </button>
      </div>
      <div class="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        <button type="button" aria-pressed={status === ''} class={`${BTN} ${status === '' ? 'bg-info-soft' : ''}`} onClick={() => setStatus('')}>
          All
        </button>
        {JOB_STATUSES.map((s) => (
          <button key={s} type="button" aria-pressed={status === s} class={`${BTN} ${status === s ? 'bg-info-soft' : ''}`} onClick={() => setStatus(s)}>
            {s} <span class="font-mono tabular-nums">{counts[s] ?? 0}</span>
          </button>
        ))}
      </div>
      <FlashLine flash={flash} />
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading jobs…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No jobs" body={status ? `No ${status} jobs.` : 'The queue has no jobs yet.'} /> : null}
      {list.items.length > 0 ? (
        <div class="overflow-x-auto border border-line">
          <table class="w-full border-collapse text-sm">
            <caption class="sr-only">Background jobs, newest first</caption>
            <thead>
              <tr>
                <Th>Created</Th>
                <Th>Kind</Th>
                <Th>Status</Th>
                <Th>Attempts</Th>
                <Th>Priority</Th>
                <Th>Run at</Th>
                <Th>Finished</Th>
                <Th>Last error</Th>
                <Th>Action</Th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((j) => (
                <>
                  <tr key={j.id} class="hover:bg-sunken">
                    <td class={`${TD} font-mono text-xs`}>{fmtTime(j.created_at)}</td>
                    <td class={TD}>{humanize(j.kind)}</td>
                    <td class={TD}>
                      <Badge tone={jobTone(j.status)}>{j.status}</Badge>
                    </td>
                    <td class={`${TD} font-mono tabular-nums`}>
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td class={`${TD} font-mono tabular-nums`}>{j.priority}</td>
                    <td class={`${TD} font-mono text-xs`}>{j.run_at ? fmtTime(j.run_at) : 'n/a'}</td>
                    <td class={`${TD} font-mono text-xs`}>{j.finished_at ? fmtTime(j.finished_at) : 'n/a'}</td>
                    <td class={`${TD} max-w-xs break-words text-xs text-danger`}>{j.last_error ?? ''}</td>
                    <td class={TD}>
                      {j.status === 'dead' ? (
                        <button type="button" class={BTN} onClick={() => setRetrying(retrying === j.id ? '' : j.id)}>
                          Retry
                        </button>
                      ) : null}
                    </td>
                  </tr>
                  {retrying === j.id ? (
                    <tr key={`${j.id}-retry`}>
                      <td colSpan={9} class={`${TD} bg-sunken`}>
                        <ReasonAction label="Retry job" tone="primary" busy={busy} help="Gives the job a fresh set of attempts. Stored in the audit log." onSubmit={(r) => void retry(j, r)} onCancel={() => setRetrying('')} />
                      </td>
                    </tr>
                  ) : null}
                </>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
    </section>
  );
}

const SERVICES: Service[] = ['identity', 'registry', 'payment', 'sms'];
const SERVICE_NOTE: Record<Service, string> = {
  identity: 'Checks that an ID, name and date of birth belong together.',
  registry: 'Holds verified income and household facts.',
  payment: 'The simulated payment rail.',
  sms: 'The simulated SMS gateway.',
};

/** The simulated services: make one slow, flaky or down, and watch cases go to a person instead of failing. */
export function MocksPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/admin/mocks')), []);
  const [reason, setReason] = useState('Demo: simulate a service problem');
  const [busy, setBusy] = useState('');
  const [flash, setFlash] = useState<Flash>(null);
  const [auto, setAuto] = useState(false);
  const reasonOk = reason.trim().length >= MIN_REASON;

  useEffect(() => {
    if (!auto) return;
    const id = window.setInterval(reload, 4000);
    return () => window.clearInterval(id);
  }, [auto, reload]);

  const send = async (key: string, body: S['MockControlIn'], okText: string) => {
    setBusy(key);
    setFlash(null);
    const res = await call(api.POST('/v1/admin/mocks', { body }));
    setBusy('');
    if (res.ok) {
      setFlash({ tone: 'ok', text: okText });
      reload();
    } else setFlash(flashFail(res.failure));
  };

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Mock services
        </h1>
        <button type="button" class={BTN} onClick={reload}>
          Refresh
        </button>
        <label class="flex items-center gap-1">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.currentTarget.checked)} />
          Refresh every 4 s
        </label>
        <button type="button" class={`${BTN_DANGER} ms-auto`} disabled={!reasonOk || busy !== ''} onClick={() => void send('reset', { reset: true, reason: reason.trim() }, 'Every control is cleared and every breaker is closed.')}>
          Reset all
        </button>
      </div>
      <p class="border border-warning-ink bg-warning-soft px-2 py-1 text-warning-ink">
        Every service here is simulated. When one is down or slow, the platform sends the case to a person instead of failing. Changes are written to the audit log.
      </p>
      <label class="flex items-center gap-2">
        <span class="shrink-0">Reason for changes</span>
        <input class={`${INPUT} flex-1`} value={reason} onInput={(e) => setReason(e.currentTarget.value)} aria-invalid={!reasonOk} />
      </label>
      <FlashLine flash={flash} />
      {loaded.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Reading the service controls…" /> : null}
      {loaded.state === 'fail' ? (
        loaded.failure.status === 404 ? (
          <ScreenState kind="not_found" density="staff" heading="h2" title="Not available here" body="Mock controls exist only in demo and dev deployments." />
        ) : (
          <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} />
        )
      ) : null}
      {loaded.state === 'ok' ? (
        <>
          <p class="text-xs text-ink-subtle">
            Transport: <Mono>{loaded.data.transport}</Mono>. {loaded.data.label}
          </p>
          <div class="grid gap-3 lg:grid-cols-2">
            {SERVICES.map((name) => {
              const svc = loaded.data.services[name];
              return svc ? <ServiceCard key={`${name}-${svc.latency_ms}-${svc.failure_rate}-${svc.down}`} name={name} svc={svc} busy={busy} reasonOk={reasonOk} onApply={(body, text) => void send(name, { reset: false, ...body, service: name, reason: reason.trim() }, text)} /> : null;
            })}
          </div>
          <SmsLog />
        </>
      ) : null}
    </section>
  );
}

function ServiceCard({ name, svc, busy, reasonOk, onApply }: { name: Service; svc: S['ServiceOut']; busy: string; reasonOk: boolean; onApply: (b: Partial<S["MockControlIn"]>, okText: string) => void }) {
  const [latency, setLatency] = useState(String(svc.latency_ms));
  const [rate, setRate] = useState(String(Math.round(svc.failure_rate * 100)));
  const b = svc.breaker as Record<string, unknown>;
  const state = String(b.state ?? 'unknown');
  const latencyN = Number(latency);
  const rateN = Number(rate);
  const valid = Number.isFinite(latencyN) && latencyN >= 0 && latencyN <= 15000 && Number.isFinite(rateN) && rateN >= 0 && rateN <= 100;
  const changed = valid && (latencyN !== svc.latency_ms || rateN / 100 !== svc.failure_rate);
  return (
    <Section
      id={`svc-${name}`}
      title={name}
      aside={
        <span class="flex items-center gap-2 text-xs">
          <Badge tone={svc.down ? 'bad' : 'good'}>{svc.down ? 'DOWN' : 'up'}</Badge>
          <Badge tone={state === 'closed' ? 'good' : state === 'open' ? 'bad' : 'warn'}>breaker {state}</Badge>
        </span>
      }
    >
      <div class="flex flex-col gap-2">
        <p class="text-xs text-ink-muted">{SERVICE_NOTE[name]}</p>
        <div class="flex flex-wrap items-center gap-3">
          <label class="flex items-center gap-1">
            Latency (ms)
            <input type="number" min={0} max={15000} class={`${INPUT} w-24 font-mono`} value={latency} onInput={(e) => setLatency(e.currentTarget.value)} />
          </label>
          <label class="flex items-center gap-1">
            Failure rate (%)
            <input type="number" min={0} max={100} class={`${INPUT} w-20 font-mono`} value={rate} onInput={(e) => setRate(e.currentTarget.value)} />
          </label>
          <button type="button" class={BTN} disabled={!changed || !reasonOk || busy !== ''} onClick={() => onApply({ latency_ms: latencyN, failure_rate: rateN / 100 }, `${name}: latency ${latencyN} ms, failure rate ${rateN}%.`)}>
            Apply
          </button>
          <button type="button" class={svc.down ? BTN_PRIMARY : BTN_DANGER} disabled={!reasonOk || busy !== ''} onClick={() => onApply({ down: !svc.down }, svc.down ? `${name} is back up.` : `${name} is down.`)}>
            {svc.down ? 'Bring up' : 'Take down'}
          </button>
        </div>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-4">
          <div>
            <dt class="text-ink-subtle">Calls</dt>
            <dd class="font-mono tabular-nums">{svc.calls}</dd>
          </div>
          <div>
            <dt class="text-ink-subtle">Failures injected</dt>
            <dd class="font-mono tabular-nums">{svc.failures_injected}</dd>
          </div>
          <div>
            <dt class="text-ink-subtle">Breaker failures</dt>
            <dd class="font-mono tabular-nums">
              {String(b.consecutive_failures ?? 0)} of {String(b.threshold ?? '?')}
            </dd>
          </div>
          <div>
            <dt class="text-ink-subtle">Rejected while open</dt>
            <dd class="font-mono tabular-nums">{String(b.rejected_while_open ?? 0)}</dd>
          </div>
        </dl>
      </div>
    </Section>
  );
}

function SmsLog() {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/admin/mocks/sms', { params: { query: { limit: 20 } } })), []);
  const rows = useMemo(() => (loaded.state === 'ok' ? loaded.data : []), [loaded]);
  return (
    <Section id="sms-log" title="Mock SMS gateway: delivered" aside={<button type="button" class="text-xs underline" onClick={reload}>refresh</button>}>
      {loaded.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Reading the gateway log…" /> : null}
      {loaded.state === 'fail' ? <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} /> : null}
      {loaded.state === 'ok' && rows.length === 0 ? <p class="text-ink-subtle">The gateway has delivered nothing yet.</p> : null}
      {rows.length > 0 ? (
        <table class="w-full border-collapse text-sm">
          <caption class="sr-only">Messages the mock SMS gateway delivered</caption>
          <thead>
            <tr>
              <Th>At</Th>
              <Th>To (masked)</Th>
              <Th>Sender</Th>
              <Th>Status</Th>
              <Th>Text</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.message_id}>
                <td class={`${TD} font-mono text-xs`}>{m.at}</td>
                <td class={TD}>
                  <Mono>
                    <span class="rh-ltr">{formatPhone(m.to)}</span>
                  </Mono>
                </td>
                <td class={TD}>{m.sender}</td>
                <td class={TD}>{m.status}</td>
                <td class={`${TD} whitespace-pre-wrap`} dir="auto">
                  {m.body}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Section>
  );
}
