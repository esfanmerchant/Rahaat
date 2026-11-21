import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, flashFail, FlashLine, LoadMore, ReasonAction, usePaged, type Flash } from '../kit';
import { activeRole, ALL_DISTRICTS, labelText, type ScamCheckOut, type ScamLabelName, type ScamReportOut } from '../scam';
import { Badge, ConfBar, fmtTime, humanize, INPUT, Mono, num, Section, TD, Th, useLoad } from '../ui';

const LABELS: ScamLabelName[] = ['relief_scam', 'phishing_link', 'advance_fee', 'impersonation', 'legit_program_message', 'unknown'];
type Route = '' | 'auto' | 'ask_more' | 'human';
type Disputed = '' | 'yes' | 'no';

const certTone = (c: string | null | undefined) => (c === 'likely_scam' ? 'bad' : c === 'might_be_scam' || c === 'not_sure' ? 'warn' : 'good');

/** Checked messages, disputes first, then every report with filters. One report opens beside the list. */
export function ScamReportsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const initialCluster = new URLSearchParams(typeof location === 'undefined' ? '' : location.search).get('cluster') ?? '';
  const [label, setLabel] = useState<'' | ScamLabelName>('');
  const [disputed, setDisputed] = useState<Disputed>('');
  const [route, setRoute] = useState<Route>('');
  const [district, setDistrict] = useState('');
  const [cluster, setCluster] = useState(initialCluster);
  const [open, setOpen] = useState<ScamReportOut | null>(null);
  const [version, setVersion] = useState(0);

  const disputes = usePaged<ScamReportOut>(
    (cursor) => call(api.GET('/v1/scam/reports', { params: { query: { limit: 20, disputed: true, ...(cursor ? { cursor: String(cursor) } : {}) } } })),
    [version],
  );
  const list = usePaged<ScamReportOut>(
    (cursor) =>
      call(
        api.GET('/v1/scam/reports', {
          params: {
            query: {
              limit: 25,
              ...(label ? { label } : {}),
              ...(disputed ? { disputed: disputed === 'yes' } : {}),
              ...(route ? { route } : {}),
              ...(district ? { district } : {}),
              ...(cluster ? { cluster_id: cluster } : {}),
              ...(cursor ? { cursor: String(cursor) } : {}),
            },
          },
        }),
      ),
    [label, disputed, route, district, cluster, version],
  );

  const changed = () => setVersion((n) => n + 1);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Scam reports
        </h1>
        <button type="button" class={BTN} onClick={changed}>
          Refresh
        </button>
        <p class="text-xs text-ink-subtle">Message text is redacted by the server and shown here as plain text.</p>
      </div>
      <div class="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div class="flex min-w-0 flex-col gap-3">
          <Section id="disputes" title="Disputed: the sender says this is real">
            {disputes.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading disputes…" /> : null}
            {disputes.status === 'fail' && disputes.failure ? <FailureState failure={disputes.failure} density="staff" heading="h2" onRetry={disputes.reload} /> : null}
            {disputes.status === 'ok' && disputes.items.length === 0 ? <p class="text-ink-muted">No disputed reports. When a citizen says "this is real, ask a person", it appears here first.</p> : null}
            {disputes.items.length > 0 ? <ReportTable items={disputes.items} openId={open?.id} onOpen={setOpen} caption="Disputed reports, newest first" /> : null}
            <LoadMore next={disputes.next} busy={disputes.loadingMore} onMore={disputes.more} />
          </Section>

          <Section id="all-reports" title="All reports">
            <div class="mb-2 flex flex-wrap items-center gap-3">
              <label class="flex items-center gap-1">
                Model label
                <select class={INPUT} value={label} onChange={(e) => setLabel(e.currentTarget.value as '' | ScamLabelName)}>
                  <option value="">Any</option>
                  {LABELS.map((l) => (
                    <option key={l} value={l}>
                      {labelText(l)}
                    </option>
                  ))}
                </select>
              </label>
              <label class="flex items-center gap-1">
                Route
                <select class={INPUT} value={route} onChange={(e) => setRoute(e.currentTarget.value as Route)}>
                  <option value="">Any</option>
                  <option value="auto">auto</option>
                  <option value="ask_more">ask more</option>
                  <option value="human">human</option>
                </select>
              </label>
              <label class="flex items-center gap-1">
                Disputed
                <select class={INPUT} value={disputed} onChange={(e) => setDisputed(e.currentTarget.value as Disputed)}>
                  <option value="">Any</option>
                  <option value="yes">Only disputed</option>
                  <option value="no">Not disputed</option>
                </select>
              </label>
              <label class="flex items-center gap-1">
                District
                <select class={INPUT} value={district} onChange={(e) => setDistrict(e.currentTarget.value)}>
                  <option value="">Any</option>
                  {ALL_DISTRICTS.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              {cluster ? (
                <span class="flex items-center gap-1 text-xs">
                  Campaign <Mono>{cluster.slice(0, 8)}</Mono>
                  <button type="button" class="underline" onClick={() => setCluster('')}>
                    clear
                  </button>
                </span>
              ) : null}
            </div>
            {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading reports…" /> : null}
            {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={list.reload} /> : null}
            {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No reports" body="Nothing matches these filters." /> : null}
            {list.items.length > 0 ? <ReportTable items={list.items} openId={open?.id} onOpen={setOpen} caption="Checked messages, newest first" /> : null}
            <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
          </Section>
        </div>
        <div class="min-w-0">
          {open ? <ReportPanel key={open.id} report={open} onClose={() => setOpen(null)} onLabelled={changed} /> : (
            <Section id="report-none" title="Report detail">
              <p class="text-ink-subtle">Open a report to see the probabilities, the signals and what each one weighs, and why the checker abstained.</p>
            </Section>
          )}
        </div>
      </div>
    </section>
  );
}

function ReportTable({ items, openId, onOpen, caption }: { items: ScamReportOut[]; openId: string | undefined; onOpen: (r: ScamReportOut) => void; caption: string }) {
  return (
    <div class="overflow-x-auto border border-line">
      <table class="w-full border-collapse text-sm">
        <caption class="sr-only">{caption}</caption>
        <thead>
          <tr>
            <Th>When</Th>
            <Th>Model said</Th>
            <Th>Confidence</Th>
            <Th>Route</Th>
            <Th>District</Th>
            <Th>Message (redacted)</Th>
            <Th>Confirmed</Th>
            <Th>Open</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id} class={openId === r.id ? 'bg-info-soft' : 'hover:bg-sunken'}>
              <td class={`${TD} whitespace-nowrap font-mono text-xs`}>{fmtTime(r.created_at).slice(5, 16)}</td>
              <td class={TD}>
                <Badge tone={certTone(r.certainty)}>{labelText(r.label)}</Badge>
                {r.disputed ? <Badge tone="info">disputed</Badge> : null}
              </td>
              <td class={TD}>
                <ConfBar value={r.confidence} />
              </td>
              <td class={TD}>{humanize(r.route)}</td>
              <td class={TD}>{r.district ?? <span class="text-ink-subtle">unknown</span>}</td>
              <td class={`${TD} max-w-xs`} title={r.text_redacted}>
                {r.text_redacted.length > 110 ? `${r.text_redacted.slice(0, 110)}…` : r.text_redacted}
              </td>
              <td class={TD}>{r.confirmed_label ? <Badge tone={r.confirmed_label === r.label ? 'good' : 'bad'}>{labelText(r.confirmed_label)}</Badge> : <span class="text-ink-subtle">not yet</span>}</td>
              <td class={TD}>
                <button type="button" class="underline" aria-label={`Open report from ${r.created_at}`} onClick={() => onOpen(r)}>
                  Open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportPanel({ report, onClose, onLabelled }: { report: ScamReportOut; onClose: () => void; onLabelled: () => void }) {
  const [detail, reload] = useLoad(() => call(api.GET('/v1/scam/reports/{report_id}', { params: { path: { report_id: report.id } } })), [report.id]);
  const [pick, setPick] = useState<ScamLabelName>(report.confirmed_label ? (report.confirmed_label as ScamLabelName) : report.label === 'unknown' ? 'legit_program_message' : (report.label as ScamLabelName));
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const canLabel = activeRole() === 'officer';
  const submit = async (reason: string) => {
    setBusy(true);
    const res = await call(api.POST('/v1/scam/reports/{report_id}/label', { params: { path: { report_id: report.id } }, body: { label: pick, reason } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setAsking(false);
    setFlash({ tone: 'ok', text: `Confirmed as ${labelText(pick)}. This feeds the mistakes ledger.` });
    onLabelled();
    reload();
  };
  return (
    <Section
      id="report-detail"
      title="Report detail"
      aside={
        <button type="button" class={BTN} onClick={onClose}>
          Close
        </button>
      }
    >
      <div class="flex flex-col gap-3">
        <div>
          <div class="text-xs font-semibold uppercase text-ink-muted">Message (redacted)</div>
          <p class="whitespace-pre-wrap break-words border border-line bg-sunken p-2">{report.text_redacted}</p>
          <p class="mt-1 text-xs text-ink-subtle">
            {report.channel}, {report.district ?? 'district unknown'}, sender {report.sender ?? 'unknown'}, {fmtTime(report.created_at)}
          </p>
        </div>
        {detail.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the analysis…" /> : null}
        {detail.state === 'fail' ? <FailureState failure={detail.failure} density="staff" heading="h2" onRetry={reload} /> : null}
        {detail.state === 'ok' ? <Analysis d={detail.data} /> : null}

        <div class="border-t border-line pt-2">
          <h3 class="text-sm font-semibold">Confirmed label</h3>
          {report.confirmed_label ? <p>Already confirmed as {labelText(report.confirmed_label)}. You can correct it with a new reason.</p> : <p class="text-ink-muted">Not confirmed yet. Confirming what the message really was is how mistakes are counted.</p>}
          {canLabel ? (
            <div class="mt-2 flex flex-col gap-2">
              <label class="flex items-center gap-2">
                It really was
                <select class={INPUT} value={pick} onChange={(e) => setPick(e.currentTarget.value as ScamLabelName)}>
                  {LABELS.map((l) => (
                    <option key={l} value={l}>
                      {labelText(l)}
                    </option>
                  ))}
                </select>
                {!asking ? (
                  <button type="button" class={BTN} onClick={() => setAsking(true)}>
                    Confirm label…
                  </button>
                ) : null}
              </label>
              {asking ? <ReasonAction label="Confirm label" tone="primary" busy={busy} help="Stored in the audit log with your name." onSubmit={(r) => void submit(r)} onCancel={() => setAsking(false)} /> : null}
            </div>
          ) : (
            <p class="text-xs text-ink-subtle">Only an officer can confirm a label.</p>
          )}
          <div class="mt-2">
            <FlashLine flash={flash} />
          </div>
        </div>
      </div>
    </Section>
  );
}

function Analysis({ d }: { d: ScamCheckOut }) {
  const det = d.detail;
  return (
    <div class="flex flex-col gap-3">
      <div>
        <div class="text-xs font-semibold uppercase text-ink-muted">What the citizen was told</div>
        <p class="font-semibold">{d.headline}</p>
        <ul class="ms-4 list-disc">
          {d.reasons.map((r) => (
            <li key={r.code}>
              {r.text} <span class="font-mono text-xs text-ink-subtle">{r.code}</span>
            </li>
          ))}
        </ul>
        <p class="text-ink-muted">{d.what_to_do}</p>
        {d.review.status !== 'none' ? (
          <p class="text-xs">
            Review: {d.review.status}
            {d.review.case_id ? <> , case <a class="underline" href={`/staff/cases/${d.review.case_id}`}>{d.review.case_id.slice(0, 8)}</a></> : null}
          </p>
        ) : null}
      </div>
      {d.urls.length ? (
        <div>
          <div class="text-xs font-semibold uppercase text-ink-muted">Links (defanged, never opened)</div>
          <ul>
            {d.urls.map((u) => (
              <li key={u.url}>
                <Mono>{u.url}</Mono> <Badge tone={u.risk === 'high' ? 'bad' : u.risk === 'medium' ? 'warn' : 'neutral'}>{u.risk}</Badge> <span class="text-xs">{u.flag_texts.join('; ')}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {det ? (
        <>
          <div>
            <div class="text-xs font-semibold uppercase text-ink-muted">Probabilities</div>
            <table class="w-full border-collapse">
              <tbody>
                {Object.entries(det.probabilities)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => (
                    <tr key={k}>
                      <td class={TD}>{labelText(k)}</td>
                      <td class={`${TD} w-40`}>
                        <ConfBar value={v} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <p class="text-xs text-ink-muted">
              Confidence {num(det.confidence)}, P(scam) {num(det.p_scam)}, model {det.model_version}, script {det.script}, sender kind {det.sender_kind}.
            </p>
          </div>
          <div>
            <div class="text-xs font-semibold uppercase text-ink-muted">Why it {det.abstained ? 'abstained' : 'did not abstain'}</div>
            {det.abstained ? <p class="font-semibold text-warning-ink">The checker said "not sure" and handed it to a person.</p> : <p class="text-ink-muted">It gave an answer.</p>}
            {det.abstain_reason ? <p>{humanize(det.abstain_reason)}</p> : null}
            <p class="text-xs text-ink-muted">
              Route costs: {Object.entries(det.route_costs).map(([k, v]) => `${humanize(k)} ${num(v)}`).join(', ') || 'none'}. Thresholds: {Object.entries(det.thresholds).map(([k, v]) => `${humanize(k)} ${num(v)}`).join(', ') || 'none'}.
            </p>
          </div>
          <div>
            <div class="text-xs font-semibold uppercase text-ink-muted">Signals and weights{det.compared_with ? ` (log-odds for the chosen class over ${labelText(det.compared_with)})` : ''}</div>
            {det.signals.length === 0 ? (
              <p class="text-ink-subtle">No signals recorded.</p>
            ) : (
              <table class="w-full border-collapse">
                <thead>
                  <tr>
                    <Th>Signal</Th>
                    <Th>Weight</Th>
                  </tr>
                </thead>
                <tbody>
                  {[...det.signals]
                    .sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight))
                    .map((s) => (
                      <tr key={s.signal}>
                        <td class={TD}>{humanize(s.signal)}</td>
                        <td class={`${TD} font-mono tabular-nums`}>{s.weight > 0 ? '+' : ''}{s.weight.toFixed(2)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
            {det.text_model_weight !== null && det.text_model_weight !== undefined ? <p class="text-xs text-ink-muted">Text model adds {det.text_model_weight.toFixed(2)}.</p> : null}
            {det.fired.length ? <p class="text-xs text-ink-muted">Fired: {det.fired.map(humanize).join(', ')}</p> : null}
          </div>
        </>
      ) : (
        <p class="text-ink-subtle">The detailed analysis is not included for this role.</p>
      )}
    </div>
  );
}
