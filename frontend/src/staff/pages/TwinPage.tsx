import { useEffect, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, flashFail, FlashLine, ReasonAction, type Flash } from '../kit';
import { activeRole } from '../scam';
import { Badge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

type Run = components['schemas']['TwinRunOut'];
type Summary = components['schemas']['DatasetSummaryOut'];
type Version = components['schemas']['RuleVersionOut'];

const OUTCOMES = ['approved', 'needs_proof', 'needs_human', 'rejected'] as const;
const sign = (n: number, d = 0): string => `${n > 0 ? '+' : ''}${n.toFixed(d)}`;
const rs = (n: number): string => `Rs ${n.toLocaleString('en-US')}`;

/** Digital Twin: run a draft rule version over past and synthetic cases before anyone publishes it. */
export function TwinPage({ initialDraft }: { initialDraft?: string }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const admin = activeRole() === 'admin';
  const [runs, reloadRuns] = useLoad(() => call(api.GET('/v1/twin/runs', { params: { query: { limit: 20 } } })), []);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-baseline gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Digital Twin
        </h1>
        <span class="text-xs text-ink-subtle">A run decides past and synthetic cases again with a draft. Nothing is sent, paid, opened or decided.</span>
      </div>
      {admin ? (
        <Section id="new-run" title="Run a draft">
          <NewRun
            initialDraft={initialDraft}
            onRan={(id) => {
              reloadRuns();
              setOpen(id);
            }}
          />
        </Section>
      ) : (
        <p class="text-ink-muted">Only an admin can run a draft. You can read the runs below.</p>
      )}
      {open ? <RunView id={open} admin={admin} onChanged={reloadRuns} onClose={() => setOpen(null)} /> : null}
      <Section id="past" title="Earlier runs">
        {runs.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading runs…" /> : null}
        {runs.state === 'fail' ? <FailureState failure={runs.failure} density="staff" heading="h2" onRetry={reloadRuns} /> : null}
        {runs.state === 'ok' && runs.data.items.length === 0 ? <ScreenState kind="empty" density="staff" title="No runs yet" body="Pick a draft above and run it." /> : null}
        {runs.state === 'ok' && runs.data.items.length > 0 ? (
          <div class="max-h-80 overflow-auto">
            <table class="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Status</Th>
                  <Th>Changed (past)</Th>
                  <Th>Changed (synthetic)</Th>
                  <Th>Flagged</Th>
                  <Th>Run</Th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr key={r.id} class={open === r.id ? 'bg-sunken' : ''}>
                    <td class={TD}>{fmtTime(r.created_at)}</td>
                    <td class={TD}>
                      <Badge tone={r.status === 'done' ? 'neutral' : r.status === 'publishing' ? 'info' : 'warn'}>{r.status}</Badge>
                    </td>
                    <td class={`${TD} tabular-nums`}>{r.changed_live ?? 'n/a'}</td>
                    <td class={`${TD} tabular-nums`}>{r.changed_synthetic ?? 'n/a'}</td>
                    <td class={TD}>{r.flagged_slices?.length ? r.flagged_slices.join(', ') : 'none'}</td>
                    <td class={TD}>
                      <button type="button" class="underline" onClick={() => setOpen(r.id)}>
                        Open <Mono>{r.id.slice(0, 8)}</Mono>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Section>
    </section>
  );
}

/** All draft versions of this department's rule sets, newest first. */
async function loadDrafts(): Promise<{ ok: true; data: Version[] } | { ok: false; failure: Parameters<typeof FailureState>[0]['failure'] }> {
  const sets = await call(api.GET('/v1/rules/sets'));
  if (!sets.ok) return sets;
  const out: Version[] = [];
  for (const s of sets.data) {
    const vs = await call(api.GET('/v1/rules/versions', { params: { query: { rule_set_id: s.id, limit: 50 } } }));
    if (!vs.ok) return vs;
    out.push(...vs.data.items.filter((v) => v.status === 'draft'));
  }
  return { ok: true, data: out };
}

function NewRun({ initialDraft, onRan }: { initialDraft?: string | undefined; onRan: (id: string) => void }) {
  const [drafts, reload] = useLoad(loadDrafts, []);
  const [pick, setPick] = useState(initialDraft ?? '');
  const [live, setLive] = useState(true);
  const [synthetic, setSynthetic] = useState(true);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  useEffect(() => {
    if (drafts.state === 'ok' && !pick && drafts.data[0]) setPick(drafts.data[0].id);
  }, [drafts, pick]);
  if (drafts.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading drafts…" />;
  if (drafts.state === 'fail') return <FailureState failure={drafts.failure} density="staff" heading="h2" onRetry={reload} />;
  if (drafts.data.length === 0) return <ScreenState kind="empty" density="staff" title="No draft versions" body="Create a draft in the rule editor first. A published version cannot be changed, so a draft is where a new rule starts." />;
  const run = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/twin/runs', { body: { draft_version_id: pick, include_live: live, include_synthetic: synthetic } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: 'The run is finished. Nothing was sent or paid.' });
    onRan(res.data.id);
  };
  return (
    <form
      class="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (pick && !busy && (live || synthetic)) void run();
      }}
    >
      <label class="flex flex-col gap-1">
        Draft version
        <select class={`${INPUT} min-w-64`} value={pick} onChange={(e) => setPick(e.currentTarget.value)}>
          {drafts.data.map((v) => (
            <option key={v.id} value={v.id}>
              Version {v.version_no} draft{v.valid ? '' : ' (not valid yet)'}
            </option>
          ))}
        </select>
      </label>
      <label class="flex items-center gap-1">
        <input type="checkbox" checked={live} onChange={(e) => setLive(e.currentTarget.checked)} /> Past decisions
      </label>
      <label class="flex items-center gap-1">
        <input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.currentTarget.checked)} /> Synthetic labelled cases
      </label>
      <button type="submit" class={BTN_PRIMARY} disabled={!pick || busy || (!live && !synthetic)}>
        {busy ? 'Running…' : 'Run in the twin'}
      </button>
      <FlashLine flash={flash} />
    </form>
  );
}

function RunView({ id, admin, onChanged, onClose }: { id: string; admin: boolean; onChanged: () => void; onClose: () => void }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/twin/runs/{run_id}', { params: { path: { run_id: id } } })), [id]);
  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the run…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" onRetry={reload} />;
  const r = loaded.data;
  return (
    <Section
      id="run"
      title={`Run ${r.id.slice(0, 8)}: version ${r.draft_version_no} against ${r.base_version_no ? `version ${r.base_version_no}` : 'nothing'}`}
      aside={
        <button type="button" class={BTN} onClick={onClose}>
          Close
        </button>
      }
    >
      <div class="flex flex-col gap-4">
        <p class="text-xs text-ink-subtle">
          {r.side_effects} Model <Mono>{r.model_version}</Mono>, status <Badge>{r.status}</Badge>, draft is <Badge>{r.draft_status}</Badge>, run {fmtTime(r.created_at)}.
        </p>
        {r.decided_reason ? <p>Decision reason: {r.decided_reason}</p> : null}
        {r.rule_changes.length > 0 ? (
          <div>
            <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Rule changes in this draft</h3>
            <ul class="mt-1 flex flex-col gap-0.5 font-mono text-xs">
              {r.rule_changes.map((c) => (
                <li key={c.path}>
                  {c.kind} {c.path}: {JSON.stringify(c.old ?? null)} to {JSON.stringify(c.new ?? null)}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p class="text-ink-muted">No rule differences against the base version.</p>
        )}
        {r.flagged_slices.length > 0 ? (
          <p role="alert" class="border border-warning-ink bg-warning-soft px-2 py-1 text-warning-ink" data-testid="flagged">
            Fairness check: the draft moves these groups by more than chance would explain: {r.flagged_slices.join(', ')}. Look at the highlighted rows below before publishing.
          </p>
        ) : (
          <p class="border border-line px-2 py-1 text-ink-muted" data-testid="flagged">
            Fairness check: no group moves by more than chance would explain.
          </p>
        )}
        {r.synthetic ? <Dataset title="Synthetic labelled cases (truth is known)" s={r.synthetic} /> : null}
        {r.live ? <Dataset title="Past decisions in this department" s={r.live} /> : null}
        <Sample rows={r.sample} />
        <Decide run={r} admin={admin} onDone={() => { reload(); onChanged(); }} />
      </div>
    </Section>
  );
}

function Dataset({ title, s }: { title: string; s: Summary }) {
  const lab = s.labelled;
  return (
    <div class="flex flex-col gap-2">
      <h3 class="text-sm font-semibold">
        {title}: {s.n} cases, {s.changed} change
        {s.skipped ? `, ${s.skipped} could not be read` : ''}
      </h3>
      <div class="grid items-start gap-4 xl:grid-cols-2">
        <table class="w-full border-collapse text-sm">
          <caption class="mb-1 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted">Outcome, before and after</caption>
          <thead>
            <tr>
              <Th>Outcome</Th>
              <Th>Before</Th>
              <Th>After</Th>
              <Th>Change</Th>
            </tr>
          </thead>
          <tbody>
            {OUTCOMES.map((o) => (
              <tr key={o}>
                <td class={TD}>{humanize(o)}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{s.outcomes_before[o] ?? 0}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{s.outcomes_after[o] ?? 0}</td>
                <td class={`${TD} text-end font-mono tabular-nums`}>{sign(s.change[o] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl class="grid grid-cols-2 gap-2">
          <Tile label="Expected cost" value={`${s.expected_cost_before.toFixed(0)} to ${s.expected_cost_after.toFixed(0)}`} sub={`${sign(s.expected_cost_change, 1)} (${sign(s.expected_cost_change_per_case, 3)} per case)`} bad={s.expected_cost_change > 0} />
          <Tile label="Payout" value={`${rs(s.payout_before_pkr)} to ${rs(s.payout_after_pkr)}`} sub={`${s.payout_after_pkr - s.payout_before_pkr >= 0 ? '+' : '-'}${rs(Math.abs(s.payout_after_pkr - s.payout_before_pkr))}`} bad={false} />
          {lab ? (
            <>
              <Tile label="Realised cost (truth known)" value={`${lab.realised_cost_before.toFixed(0)} to ${lab.realised_cost_after.toFixed(0)}`} sub={sign(lab.realised_cost_change, 1)} bad={lab.realised_cost_change > 0} />
              <Tile
                label="Wrong approvals and rejections"
                value={`${lab.before.false_approvals}/${lab.before.false_rejections} to ${lab.after.false_approvals}/${lab.after.false_rejections}`}
                sub={`not automatic although OK: ${lab.before.not_automatic_although_ok} to ${lab.after.not_automatic_although_ok}`}
                bad={lab.after.false_approvals > lab.before.false_approvals}
              />
            </>
          ) : null}
          {s.base_differs_from_stored ? <Tile label="Base differs from stored" value={String(s.base_differs_from_stored)} sub="decisions the base version would now decide differently" bad /> : null}
        </dl>
      </div>
      <Slices s={s} />
    </div>
  );
}

function Tile({ label, value, sub, bad }: { label: string; value: string; sub: string; bad: boolean }) {
  return (
    <div class="border border-line px-2 py-1">
      <dt class="text-xs text-ink-subtle">{label}</dt>
      <dd class="font-mono text-sm font-semibold tabular-nums">{value}</dd>
      <dd class={`text-xs ${bad ? 'text-danger' : 'text-ink-muted'}`}>{sub}</dd>
    </div>
  );
}

function Slices({ s }: { s: Summary }) {
  const groups = Object.entries(s.slices);
  if (groups.length === 0) return null;
  return (
    <details open={s.flagged_slices.length > 0}>
      <summary class="cursor-pointer text-xs font-semibold uppercase tracking-wide text-ink-muted">Fairness slices ({s.flagged_slices.length} flagged)</summary>
      <div class="mt-1 max-h-72 overflow-auto">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr>
              <Th>Slice</Th>
              <Th>Cases</Th>
              <Th>Approve before</Th>
              <Th>Approve after</Th>
              <Th>Change</Th>
              <Th>Noise (2 SE)</Th>
              <Th>Needs person change</Th>
              <Th>Flag</Th>
            </tr>
          </thead>
          <tbody>
            {groups.flatMap(([name, rows]) =>
              rows.map((r) => (
                <tr key={`${name}-${r.value}`} class={r.flagged ? 'bg-warning-soft' : ''}>
                  <td class={TD}>
                    {name}: {r.value}
                  </td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{r.n}</td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{(r.approve_rate_before * 100).toFixed(1)}%</td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{(r.approve_rate_after * 100).toFixed(1)}%</td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{sign(r.approve_change * 100, 1)} pts</td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{(r.noise * 100).toFixed(1)} pts</td>
                  <td class={`${TD} text-end font-mono tabular-nums`}>{sign(r.human_change * 100, 1)} pts</td>
                  <td class={TD}>{r.flagged ? <Badge tone="warn">flagged</Badge> : 'ok'}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Sample({ rows }: { rows: Run['sample'] }) {
  if (rows.length === 0) return <p class="text-ink-muted">No case changes outcome with this draft.</p>;
  return (
    <div>
      <h3 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">A sample of cases that change ({rows.length})</h3>
      <div class="mt-1 max-h-72 overflow-auto">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr>
              <Th>Case</Th>
              <Th>Group</Th>
              <Th>Before</Th>
              <Th>After</Th>
              <Th>Why it changed</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={`${c.dataset}-${c.ref}`}>
                <td class={TD}>
                  <Mono>{c.ref.slice(0, 12)}</Mono> <span class="text-xs text-ink-subtle">{c.dataset}</span>
                </td>
                <td class={`${TD} text-xs`}>{Object.values(c.slices).filter(Boolean).join(', ')}</td>
                <td class={TD}>
                  {humanize(c.before.outcome)} <span class="text-xs text-ink-subtle">cost {c.before.expected_cost.toFixed(2)}</span>
                </td>
                <td class={TD}>
                  {humanize(c.after.outcome)} <span class="text-xs text-ink-subtle">cost {c.after.expected_cost.toFixed(2)}</span>
                </td>
                <td class={`${TD} text-xs`}>{c.after.reasons.map(humanize).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Decide({ run, admin, onDone }: { run: Run; admin: boolean; onDone: () => void }) {
  const [mode, setMode] = useState<'publish' | 'discard' | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  if (!admin) return null;
  if (run.status !== 'done') return <p class="text-ink-muted">This run is {run.status}. {run.status === 'publishing' ? 'A second admin can publish the draft in the rule editor.' : 'Nothing more to decide.'}</p>;
  const act = async (kind: 'request-publish' | 'discard', reason: string) => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST(kind === 'discard' ? '/v1/twin/runs/{run_id}/discard' : '/v1/twin/runs/{run_id}/request-publish', { params: { path: { run_id: run.id } }, body: { reason } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: kind === 'discard' ? 'Recorded: this draft does not go ahead.' : 'Sent for approval. A second admin must publish it in the rule editor.' });
    setMode(null);
    onDone();
  };
  return (
    <div class="flex flex-col gap-2 border-t border-line pt-2">
      <div class="flex flex-wrap gap-2">
        <button type="button" class={BTN_PRIMARY} onClick={() => setMode('publish')} disabled={busy}>
          Request publish (four eyes)
        </button>
        <button type="button" class={BTN} onClick={() => setMode('discard')} disabled={busy}>
          Discard this draft
        </button>
        <a href="/staff/rules" class="self-center text-xs">
          Open the rule editor
        </a>
      </div>
      {mode ? (
        <ReasonAction
          label={mode === 'publish' ? 'Send for second approval' : 'Record discard'}
          tone={mode === 'publish' ? 'primary' : 'danger'}
          busy={busy}
          help={mode === 'publish' ? 'A different admin must publish it. Your reason goes to them and to the audit log.' : 'Stored in the audit log.'}
          onSubmit={(reason) => void act(mode === 'publish' ? 'request-publish' : 'discard', reason)}
          onCancel={() => setMode(null)}
        />
      ) : null}
      <FlashLine flash={flash} />
    </div>
  );
}
