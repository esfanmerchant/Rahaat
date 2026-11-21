import { useEffect, useRef, useState } from 'preact/hooks';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { activeRole } from '../scam';
import { Badge, ConfBar, fmtTime, humanize, Mono, Section, TD, Th, useLoad } from '../ui';
import { failureText } from '../kit';
import { HeatBar } from '../viz';
import { getAnomalies, runAnomalyScan, type DetectorStatus, type Flag } from './wpdApi';

/**
 * Anomaly flags: patterns across applications that no single decision shows. A flag is a reason for a person to look,
 * never a decision about anyone. Detection details are for staff only; citizens hear "a person will check".
 */

const ORDER: DetectorStatus['detector'][] = ['shared_payout', 'helper_burst', 'repeated_identity', 'application_spike'];
const REASON_TEXT: Record<string, string> = {
  thin_baseline: 'Not enough history to tell a spike from a quiet start.',
  thin_helper_data: 'Too few helper submissions to compare against.',
  no_payout_data: 'No payout accounts on file yet.',
  no_identity_data: 'No ID numbers on file yet.',
  no_district_data: 'No district on the applications yet.',
};
const CHIP_LABEL: Record<string, string> = {
  account: 'account',
  people: 'people',
  households: 'households',
  districts: 'districts',
  district: 'district',
  day: 'day',
  applications: 'applications',
  usual_per_day: 'usual / day',
  robust_z: 'robust z',
  baseline_days: 'baseline days',
  helper: 'helper',
  families: 'families',
  minutes: 'minutes',
  from: 'from',
  id: 'ID',
  attempts: 'attempts',
  refused: 'refused',
};
const STATE_TONE = { flagged: 'bad', clear: 'good', abstained: 'warn' } as const;

export function AnomaliesPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = activeRole();
  const [data, reload] = useLoad(() => getAnomalies(), []);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);
  const before = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (data.state === 'ok' && !busy) before.current = data.data.last_scan?.run_id ?? null;
  }, [data, busy]);

  // After "Run now" the job runs in the background; read the page again until a newer run shows up.
  const waitForRun = (attempt: number) => {
    void getAnomalies().then((res) => {
      const newest = res.ok ? (res.data.last_scan?.run_id ?? null) : before.current;
      if (res.ok && newest !== before.current) {
        setBusy(false);
        const s = res.data.last_scan;
        setMessage({ tone: 'ok', text: s ? `Run finished at ${fmtTime(s.ran_at)}.` : 'Run finished.' });
        reload();
      } else if (attempt >= 20) {
        setBusy(false);
        setMessage({ tone: 'err', text: 'The run is still queued. Refresh in a moment; nothing was lost.' });
      } else {
        timer.current = window.setTimeout(() => waitForRun(attempt + 1), 1000);
      }
    });
  };

  const runNow = async () => {
    setBusy(true);
    setMessage(null);
    const res = await runAnomalyScan();
    if (!res.ok) {
      setBusy(false);
      setMessage({ tone: 'err', text: failureText(res.failure) });
      return;
    }
    waitForRun(0);
  };

  const flagsBy = (name: string): Flag[] => (data.state === 'ok' ? data.data.flags.filter((f) => f.detector === name) : []);

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-4">
      <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-xl font-black tracking-tight">
          Anomalies
        </h1>
        <span class="text-xs text-ink-subtle">Patterns across applications. A flag is a reason for a person to look, never a decision about anyone.</span>
        <div class="ms-auto flex items-center gap-2">
          {role === 'admin' ? (
            <button
              type="button"
              class="h-8 rounded-sm border border-primary-strong bg-primary px-3 text-xs font-semibold text-white hover:bg-primary-strong disabled:opacity-60"
              disabled={busy}
              onClick={() => void runNow()}
            >
              {busy ? 'Running…' : 'Run detection now'}
            </button>
          ) : null}
          <button type="button" class="h-8 rounded-sm border border-line-strong px-3 text-xs hover:bg-sunken" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>

      {message ? (
        <p role={message.tone === 'err' ? 'alert' : 'status'} class={`border px-2 py-1 text-sm ${message.tone === 'err' ? 'border-danger bg-danger-soft text-danger' : 'border-primary bg-primary-soft text-primary-strong'}`}>
          {message.text}
        </p>
      ) : null}

      {data.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Reading the last detection run…" /> : null}
      {data.state === 'fail' ? <FailureState failure={data.failure} density="staff" onRetry={reload} /> : null}
      {data.state === 'ok' ? (
        <>
          {data.data.last_scan === null ? (
            <ScreenState
              kind="empty"
              density="staff"
              heading="h2"
              title="Detection has not run yet"
              body={role === 'admin' ? 'Press "Run detection now" to read the applications once. Nothing is flagged until then.' : 'An admin runs detection, or it runs after new applications. Nothing is flagged until then.'}
            />
          ) : (
            <>
              <p class="text-xs text-ink-subtle">
                Last run {fmtTime(data.data.last_scan.ran_at)} ({data.data.last_scan.trigger}): {data.data.last_scan.applications_scanned} applications read, {data.data.last_scan.cases_opened} cases opened,{' '}
                {data.data.last_scan.cases_refreshed} refreshed, {data.data.last_scan.suppressed} already reviewed. People who withdrew consent are left out.
              </p>
              <ul class="grid gap-3 md:grid-cols-2 2xl:grid-cols-4" aria-label="Detectors">
                {ORDER.map((name) => {
                  const d = data.data.last_scan?.detectors.find((x) => x.detector === name);
                  if (!d) return null;
                  return <DetectorCard key={name} d={d} active={data.data.counts[name] ?? 0} />;
                })}
              </ul>
            </>
          )}

          {data.data.flags.length === 0 && data.data.last_scan !== null ? (
            <ScreenState kind="empty" density="staff" heading="h2" title="No flags" body="Every detector that had enough data found nothing unusual. A detector that abstained is shown above with the reason." />
          ) : null}

          {ORDER.map((name) => {
            const rows = flagsBy(name);
            if (rows.length === 0) return null;
            return (
              <Section key={name} id={`flags-${name}`} title={`${titleOf(name)} (${rows.length})`}>
                <FlagTable rows={rows} role={role} />
              </Section>
            );
          })}
          <p class="text-xs text-ink-subtle">{data.data.note}</p>
        </>
      ) : null}
    </section>
  );
}

/** "2026-11-21T14:30+00:00" reads better as "2026-11-21 14:30 UTC". */
const chipValue = (key: string, value: string | number): string =>
  key === 'from' ? String(value).replace('T', ' ').replace(/(\d\d:\d\d)(:\d\d)?(\+00:00|Z)?$/, '$1 UTC') : String(value);

const titleOf = (name: string): string =>
  ({ shared_payout: 'Shared payout account', application_spike: 'Application spikes', helper_burst: 'Helper bursts', repeated_identity: 'Repeated ID numbers' })[name] ?? name;

function DetectorCard({ d, active }: { d: DetectorStatus; active: number }) {
  const points = Object.entries(d.data_points).map(([k, v]) => `${humanize(k)} ${String(v)}`).join(', ');
  return (
    <li class={`st-tile st-tone-${d.status === 'flagged' ? 'bad' : d.status === 'abstained' ? 'warn' : 'ok'} flex flex-col gap-1 p-3`} data-testid={`detector-${d.detector}`}>
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs font-bold uppercase tracking-widest text-ink-muted">{titleOf(d.detector)}</p>
        <Badge tone={STATE_TONE[d.status]}>{d.status}</Badge>
      </div>
      <p class="rh-num text-3xl font-black leading-none">{active}</p>
      <p class="text-xs text-ink-subtle">open flags{d.flags > 0 ? `, ${d.flags} in the last run` : ''}</p>
      {d.status === 'abstained' ? (
        <p class="text-xs text-warning-ink">Abstained: {(d.abstained_reason && REASON_TEXT[d.abstained_reason]) || humanize(d.abstained_reason ?? 'not enough data')}</p>
      ) : null}
      <p class="text-xs text-ink-muted">{points}</p>
    </li>
  );
}

function FlagTable({ rows, role }: { rows: Flag[]; role: string }) {
  return (
    <div class="overflow-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr>
            <Th>Evidence</Th>
            <Th>Score</Th>
            <Th>Priority</Th>
            <Th>Cheapest check</Th>
            <Th>Case</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.case_id}>
              <td class={TD}>
                <div class="flex flex-wrap gap-1">
                  {Object.entries(f.evidence).map(([k, v]) => (
                    <span key={k} class="st-chip font-mono">
                      {CHIP_LABEL[k] ?? humanize(k)}: {chipValue(k, v)}
                    </span>
                  ))}
                  <span class="st-chip info font-mono" title={f.evidence_ids.slice(0, 8).join(', ')}>
                    {f.evidence_count} applications
                  </span>
                </div>
              </td>
              <td class={TD}>
                <ConfBar value={f.confidence} />
              </td>
              <td class={TD}>
                <HeatBar priority={f.priority} />
              </td>
              <td class={`${TD} max-w-md text-xs text-ink-muted`}>{f.cheapest_check ?? 'n/a'}</td>
              <td class={TD}>
                <div class="flex flex-col gap-0.5">
                  <Badge tone={f.case_status === 'resolved' || f.case_status === 'closed' ? 'good' : 'warn'}>
                    {humanize(f.case_status)}
                    {f.resolution ? `, ${f.resolution === 'rejected' ? 'confirmed' : 'dismissed'}` : ''}
                  </Badge>
                  {role === 'officer' ? (
                    <a href={`/staff/cases/${f.case_id}`} class="text-xs">
                      Open the case
                    </a>
                  ) : (
                    <Mono title="Only an officer opens the case">{f.case_id.slice(0, 8)}</Mono>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
