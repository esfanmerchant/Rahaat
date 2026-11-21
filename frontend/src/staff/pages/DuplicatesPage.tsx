import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, flashFail, FlashLine, LoadMore, ReasonAction, usePaged, type Flash } from '../kit';
import { Badge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

interface PersonView {
  readable: boolean;
  id?: string;
  full_name?: string | null;
  full_name_ur?: string | null;
  dob?: string | null;
  gender?: string | null;
  district?: string | null;
  status?: string;
}
interface Candidate {
  id: string;
  status: string;
  band: string;
  score: number;
  case_id: string | null;
  created_at: string;
  resolved_at: string | null;
  person_a: PersonView;
  person_b: PersonView;
  reasons: string[];
  evidence?: Record<string, unknown>;
  comparison_now?: { fields?: Record<string, string>; weights?: Record<string, number>; conflicts?: string[]; reasons?: string[]; name_score?: number; score?: number; band?: string; corroborated?: boolean };
}

const STATUSES = ['open', 'linked', 'rejected', 'reversed', 'all'] as const;
type Status = (typeof STATUSES)[number];
const STATUS_WORDS: Record<string, string> = { open: 'waiting for a person', linked: 'linked as one person', rejected: 'marked as two people', reversed: 'link reversed' };

/** Possible duplicate people. The system never merges on its own: an officer decides, with a reason, and a link can be reversed. */
export function DuplicatesPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [status, setStatus] = useState<Status>('open');
  const [open, setOpen] = useState<string | null>(null);
  const list = usePaged<Candidate>(
    (cursor) => call(api.GET('/v1/duplicates', { params: { query: { status, limit: 25, ...(cursor ? { cursor: String(cursor) } : {}) } } })) as never,
    [status],
  );
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Possible duplicates
        </h1>
        <label class="flex items-center gap-1">
          Show
          <select class={INPUT} value={status} onChange={(e) => { setStatus(e.currentTarget.value as Status); setOpen(null); }}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      {list.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading pairs…" /> : null}
      {list.status === 'fail' && list.failure ? <FailureState failure={list.failure} density="staff" onRetry={list.reload} /> : null}
      {list.status === 'ok' && list.items.length === 0 ? <ScreenState kind="empty" density="staff" title="No pairs here" body={status === 'open' ? 'No two records are waiting for a person to compare them.' : 'No pair has this status.'} /> : null}
      {list.status === 'ok' && list.items.length > 0 ? (
        <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div class="overflow-auto">
            <table class="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <Th>Found</Th>
                  <Th>Band</Th>
                  <Th>Score</Th>
                  <Th>Status</Th>
                  <Th>Why</Th>
                  <Th>Review</Th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((c) => (
                  <tr key={c.id} class={open === c.id ? 'bg-sunken' : ''}>
                    <td class={TD}>{fmtTime(c.created_at)}</td>
                    <td class={TD}>
                      <Badge tone={c.band === 'possible' ? 'warn' : 'neutral'}>{c.band}</Badge>
                    </td>
                    <td class={`${TD} font-mono tabular-nums`}>{c.score.toFixed(2)}</td>
                    <td class={TD}>{STATUS_WORDS[c.status] ?? c.status}</td>
                    <td class={`${TD} text-xs`}>{c.reasons.map(humanize).join('; ') || 'n/a'}</td>
                    <td class={TD}>
                      <button type="button" class="underline" onClick={() => setOpen(c.id)}>
                        Compare <Mono>{c.id.slice(0, 8)}</Mono>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <LoadMore next={list.next} busy={list.loadingMore} onMore={list.more} />
          </div>
          {open ? <Detail id={open} onChanged={list.reload} /> : <p class="text-ink-muted">Pick a pair to see what agrees and what does not.</p>}
        </div>
      ) : null}
    </section>
  );
}

const FIELD_WORDS: Record<string, string> = { same: 'agree', different: 'differ', unknown: 'unknown' };

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/duplicates/{candidate_id}', { params: { path: { candidate_id: id } } })) as never as Promise<import('../../shared/api/problem').Result<Candidate>>, [id]);
  const [mode, setMode] = useState<'link' | 'distinct' | 'unlink' | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the pair…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" onRetry={reload} />;
  const c = loaded.data;
  const cmp = c.comparison_now ?? (c.evidence as Candidate['comparison_now']) ?? {};
  const fields = Object.entries(cmp.fields ?? {});
  const act = async (kind: 'link' | 'distinct' | 'unlink', reason: string) => {
    setBusy(true);
    setFlash(null);
    const path = kind === 'link' ? '/v1/duplicates/{candidate_id}/link' : kind === 'distinct' ? '/v1/duplicates/{candidate_id}/distinct' : '/v1/duplicates/{candidate_id}/unlink';
    const res = await call(api.POST(path, { params: { path: { candidate_id: id } }, body: { reason } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: kind === 'link' ? 'Linked as one person. You can reverse this.' : kind === 'distinct' ? 'Marked as two different people.' : 'The link is reversed.' });
    setMode(null);
    reload();
    onChanged();
  };
  const person = (p: PersonView, label: string) => (
    <div class="border border-line p-2">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">{label}</h3>
      {p.readable ? (
        <dl class="mt-1 grid grid-cols-[6rem_1fr] gap-x-2 gap-y-0.5">
          <dt class="text-ink-subtle">Name</dt>
          <dd>{p.full_name ?? 'n/a'}</dd>
          <dt class="text-ink-subtle">Name (Urdu)</dt>
          <dd lang="ur" dir="rtl" class="text-start">{p.full_name_ur ?? 'n/a'}</dd>
          <dt class="text-ink-subtle">Born</dt>
          <dd>{p.dob ?? 'n/a'}</dd>
          <dt class="text-ink-subtle">Gender</dt>
          <dd>{p.gender ?? 'n/a'}</dd>
          <dt class="text-ink-subtle">District</dt>
          <dd>{p.district ?? 'n/a'}</dd>
        </dl>
      ) : (
        <p class="text-ink-muted">Not shown: this person's consent does not allow it.</p>
      )}
    </div>
  );
  return (
    <Section id="pair" title={`Pair ${c.id.slice(0, 8)}: ${c.band}, ${STATUS_WORDS[c.status] ?? c.status}`}>
      <div class="flex flex-col gap-3">
        <div class="grid gap-2 md:grid-cols-2">
          {person(c.person_a, 'Record A')}
          {person(c.person_b, 'Record B')}
        </div>
        <table class="w-full max-w-lg border-collapse text-sm">
          <caption class="mb-1 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted">What agrees and what does not (name score {cmp.name_score?.toFixed(2) ?? 'n/a'}, overall {cmp.score?.toFixed(2) ?? 'n/a'})</caption>
          <thead>
            <tr>
              <Th>Field</Th>
              <Th>Result</Th>
              <Th>Weight</Th>
            </tr>
          </thead>
          <tbody>
            {fields.map(([f, v]) => (
              <tr key={f} class={v === 'different' ? 'bg-danger-soft' : v === 'same' ? 'bg-primary-soft' : ''}>
                <td class={TD}>{humanize(f)}</td>
                <td class={TD}>{FIELD_WORDS[v] ?? v}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{cmp.weights?.[f]?.toFixed(1) ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p class="text-xs text-ink-muted">
          {cmp.corroborated ? 'An identifier agrees.' : 'No identifier agrees, so a name alone is not enough to link.'} {cmp.conflicts?.length ? `Conflicts: ${cmp.conflicts.join(', ')}.` : 'Nothing contradicts.'} Reasons: {(cmp.reasons ?? c.reasons).map(humanize).join('; ') || 'none'}.
        </p>
        <div class="flex flex-wrap gap-2">
          {c.status === 'open' || c.status === 'rejected' || c.status === 'reversed' ? (
            <button type="button" class={BTN_PRIMARY} onClick={() => setMode('link')} disabled={busy}>
              Link: same person
            </button>
          ) : null}
          {c.status === 'open' ? (
            <button type="button" class={BTN} onClick={() => setMode('distinct')} disabled={busy}>
              Mark distinct: two people
            </button>
          ) : null}
          {c.status === 'linked' ? (
            <button type="button" class={BTN} onClick={() => setMode('unlink')} disabled={busy}>
              Unlink
            </button>
          ) : null}
          {c.case_id ? <a class="self-center" href={`/staff/cases/${c.case_id}`}>Open the case</a> : null}
        </div>
        {mode ? <ReasonAction label={mode === 'link' ? 'Link records' : mode === 'distinct' ? 'Mark distinct' : 'Unlink'} tone={mode === 'link' ? 'primary' : 'neutral'} busy={busy} onSubmit={(r) => void act(mode, r)} onCancel={() => setMode(null)} /> : null}
        <FlashLine flash={flash} />
      </div>
    </Section>
  );
}
