import { useMemo, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN } from '../kit';
import { isScamKind, labelText, type ScamReportOut } from '../scam';
import { Badge, fmtTime, Section, TD, Th, useLoad } from '../ui';

const PAGE = 100;
const MAX_PAGES = 20;

interface Loaded {
  reports: ScamReportOut[];
  /** True when there were more reports than the page cap. */
  truncated: boolean;
}

async function loadAll(): Promise<Result<Loaded>> {
  const reports: ScamReportOut[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page++) {
    const res = await call(api.GET('/v1/scam/reports', { params: { query: { limit: PAGE, ...(cursor ? { cursor } : {}) } } }));
    if (!res.ok) return res;
    reports.push(...res.data.items);
    if (!res.data.next_cursor) return { ok: true, data: { reports, truncated: false } };
    cursor = res.data.next_cursor;
  }
  return { ok: true, data: { reports, truncated: true } };
}

type Kind = 'false_alarm' | 'missed' | 'wrong_type' | 'not_sure' | 'disputed';

const KINDS: { kind: Kind; title: string; cost: string }[] = [
  {
    kind: 'false_alarm',
    title: 'False alarms on real messages',
    cost: 'A real message was called a scam. The person may ignore a genuine relief notice or payment, or feel accused. Blocking a real person is a cost, not a safe default.',
  },
  {
    kind: 'missed',
    title: 'Missed scams',
    cost: 'A scam was passed as fine or unknown. The person may send a fee or give a PIN to a scammer. This is the costliest mistake.',
  },
  {
    kind: 'wrong_type',
    title: 'Scam, wrong type',
    cost: 'It was a scam but the checker named another kind. The warning text and the campaign grouping can be off; the person is still protected.',
  },
  {
    kind: 'not_sure',
    title: 'Not sure (abstained)',
    cost: 'The checker said it did not know and handed over. Cost is a person\'s time and a delay for the citizen; it is the honest choice, not an error to hide.',
  },
  {
    kind: 'disputed',
    title: 'Disputed by the sender',
    cost: 'The citizen said "this is real, ask a person". Each one needs an officer and shows where the checker may be over-cautious.',
  },
];

function classify(r: ScamReportOut): Kind[] {
  const kinds: Kind[] = [];
  const confirmed = r.confirmed_label;
  if (confirmed) {
    if (confirmed === 'legit_program_message' && isScamKind(r.label)) kinds.push('false_alarm');
    else if (isScamKind(confirmed) && !isScamKind(r.label)) kinds.push('missed');
    else if (isScamKind(confirmed) && isScamKind(r.label) && confirmed !== r.label) kinds.push('wrong_type');
  }
  if (r.certainty === 'not_sure') kinds.push('not_sure');
  if (r.disputed) kinds.push('disputed');
  return kinds;
}

const KIND_TONE: Record<Kind, 'bad' | 'warn' | 'info'> = { false_alarm: 'bad', missed: 'bad', wrong_type: 'warn', not_sure: 'warn', disputed: 'info' };
const KIND_SHORT: Record<Kind, string> = { false_alarm: 'false alarm', missed: 'missed scam', wrong_type: 'wrong type', not_sure: 'not sure', disputed: 'disputed' };

/** Where the checker was wrong or unsure, built only from the reports API. */
export function MistakesPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [data, reload] = useLoad(loadAll, []);
  const [filter, setFilter] = useState<Kind | ''>('');
  const stats = useMemo(() => {
    if (data.state !== 'ok') return null;
    const rows = data.data.reports.map((r) => ({ r, kinds: classify(r) }));
    const count = (k: Kind) => rows.filter((x) => x.kinds.includes(k)).length;
    const confirmed = data.data.reports.filter((r) => r.confirmed_label);
    const right = confirmed.filter((r) => r.confirmed_label === r.label).length;
    return {
      rows,
      count,
      total: rows.length,
      confirmed: confirmed.length,
      right,
      disputedOpen: data.data.reports.filter((r) => r.disputed && !r.confirmed_label).length,
    };
  }, [data]);

  const shown = stats ? stats.rows.filter((x) => x.kinds.length > 0 && (filter === '' || x.kinds.includes(filter))) : [];
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Mistakes ledger
        </h1>
        <button type="button" class={BTN} onClick={reload}>
          Refresh
        </button>
      </div>
      {data.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Reading every checked message…" /> : null}
      {data.state === 'fail' ? <FailureState failure={data.failure} density="staff" heading="h2" onRetry={reload} /> : null}
      {data.state === 'ok' && stats ? (
        <>
          <p class="max-w-3xl text-ink-muted">
            This page lists where the scam checker was wrong or unsure, using {stats.total} checked messages
            {data.data.truncated ? ` (the newest ${PAGE * MAX_PAGES}; older ones are not counted)` : ''}. A mistake is only known when an officer has confirmed what a message really was, so the first two counts grow as officers confirm labels in{' '}
            <a class="underline" href="/staff/scam-reports">
              Scam reports
            </a>
            .
          </p>
          {stats.total === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No checked messages yet" body="Nothing to count." /> : null}
          <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {KINDS.map((k) => (
              <button
                key={k.kind}
                type="button"
                aria-pressed={filter === k.kind}
                onClick={() => setFilter(filter === k.kind ? '' : k.kind)}
                class={`flex flex-col gap-1 border p-3 text-start ${filter === k.kind ? 'border-ink bg-info-soft' : 'border-line-strong hover:bg-sunken'}`}
              >
                <span class="text-xs font-semibold uppercase tracking-wide text-ink-muted">{k.title}</span>
                <span class="text-3xl font-semibold tabular-nums">{stats.count(k.kind)}</span>
                <span class="text-xs text-ink-muted">{k.cost}</span>
              </button>
            ))}
          </div>

          <Section id="what-we-know" title="What these numbers can and cannot say">
            <ul class="ms-4 list-disc space-y-1">
              <li>
                {stats.confirmed} of {stats.total} messages have a confirmed label; the checker agreed with the officer on {stats.right}
                {stats.confirmed > 0 ? ` (${Math.round((stats.right / stats.confirmed) * 100)}%)` : ''}. Officers tend to confirm the doubtful ones, so this is not the checker's overall accuracy.
              </li>
              <li>{stats.total - stats.confirmed} messages are unconfirmed. We do not know whether the checker was right on them, and this page does not guess.</li>
              <li>{stats.disputedOpen} disputed reports are still waiting for an officer.</li>
              <li>
                Not available from the API: the rupee loss behind a missed scam, and whether a flagged citizen was actually blocked from a service. The costs above are the planning costs from the cost matrix, not measured harm.
              </li>
            </ul>
          </Section>

          <Section id="mistake-list" title={filter ? `${KINDS.find((k) => k.kind === filter)?.title}` : 'Every mistake and doubt'}>
            {shown.length === 0 ? (
              <p class="text-ink-muted">{filter ? 'None of this kind yet.' : 'No mistakes or doubts recorded yet.'}</p>
            ) : (
              <div class="overflow-x-auto border border-line">
                <table class="w-full border-collapse text-sm">
                  <caption class="sr-only">Reports where the checker was wrong or unsure</caption>
                  <thead>
                    <tr>
                      <Th>Kind</Th>
                      <Th>When</Th>
                      <Th>Model said</Th>
                      <Th>Officer confirmed</Th>
                      <Th>Message (redacted)</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map(({ r, kinds }) => (
                      <tr key={r.id} class="hover:bg-sunken">
                        <td class={TD}>
                          {kinds.map((k) => (
                            <Badge key={k} tone={KIND_TONE[k]}>
                              {KIND_SHORT[k]}
                            </Badge>
                          ))}
                        </td>
                        <td class={`${TD} whitespace-nowrap font-mono text-xs`}>{fmtTime(r.created_at).slice(5, 16)}</td>
                        <td class={TD}>{labelText(r.label)}</td>
                        <td class={TD}>{r.confirmed_label ? labelText(r.confirmed_label) : <span class="text-ink-subtle">not yet</span>}</td>
                        <td class={`${TD} max-w-xl`}>{r.text_redacted}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      ) : null}
    </section>
  );
}
