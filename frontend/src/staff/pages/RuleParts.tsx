import { useMemo, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { BTN, BTN_PRIMARY, flashFail, FlashLine, type Flash } from '../kit';
import { words } from '../ruleText';
import { SAMPLE_CASE } from '../sampleCase';
import { Badge, humanize, INPUT, Mono, TD, Th, useLoad } from '../ui';

type S = components['schemas'];
export type Issue = S['ValidationIssue'];
export type Dsl = Record<string, unknown>;
type Rule = { id?: string; hard?: boolean; label_en?: string; label_ur?: string; expr?: unknown };

const DOC_KINDS = ['rahat_id', 'income_proof', 'other'];
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function IssueList({ issues }: { issues: Issue[] }) {
  return (
    <div role="alert" class="border border-danger bg-danger-soft p-2">
      <p class="font-semibold text-danger">
        {issues.length} problem{issues.length === 1 ? '' : 's'} to fix
      </p>
      <ul class="mt-1 flex flex-col gap-1">
        {issues.map((e, i) => (
          <li key={`${e.path}-${i}`} class="flex flex-wrap gap-2">
            <Mono>{e.path}</Mono>
            <Badge tone="bad">{e.code}</Badge>
            <span>{e.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RuleForm({ dsl, editable, issues, onChange }: { dsl: Dsl; editable: boolean; issues: Issue[]; onChange: (d: Dsl) => void }) {
  const params = (dsl.params && typeof dsl.params === 'object' ? dsl.params : {}) as Record<string, unknown>;
  const rules = (Array.isArray(dsl.all) ? dsl.all : []) as Rule[];
  const docs = (Array.isArray(dsl.required_docs) ? dsl.required_docs : []) as string[];
  const [newParam, setNewParam] = useState('');
  const set = (patch: Dsl) => onChange({ ...clone(dsl), ...patch });
  const setRule = (i: number, patch: Rule) => set({ all: rules.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const move = (i: number, d: number) => {
    const next = [...rules];
    const [item] = next.splice(i, 1);
    if (item) next.splice(i + d, 0, item);
    set({ all: next });
  };
  const known = new Set(['params', 'required_docs', 'payment_pkr', 'all']);

  return (
    <div class="flex flex-col gap-3">
      <div class="grid gap-3 md:grid-cols-2">
        <fieldset class="border border-line p-2">
          <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Parameters</legend>
          <div class="flex flex-col gap-1">
            {Object.entries(params).map(([k, val]) => (
              <label key={k} class="flex items-center gap-2">
                <span class="w-44 shrink-0 font-mono text-xs">{k}</span>
                <input
                  type="number"
                  step="any"
                  class={`${INPUT} w-32 font-mono`}
                  value={String(val)}
                  disabled={!editable}
                  onInput={(e) => {
                    const n = e.currentTarget.valueAsNumber;
                    if (!Number.isNaN(n)) set({ params: { ...params, [k]: n } });
                  }}
                />
                {editable ? (
                  <button
                    type="button"
                    class="text-xs underline"
                    onClick={() => {
                      const p = { ...params };
                      delete p[k];
                      set({ params: p });
                    }}
                  >
                    remove
                  </button>
                ) : null}
              </label>
            ))}
            {Object.keys(params).length === 0 ? <p class="text-ink-subtle">No parameters.</p> : null}
            {editable ? (
              <div class="mt-1 flex items-center gap-2">
                <input class={`${INPUT} w-44 font-mono`} aria-label="New parameter name" value={newParam} onInput={(e) => setNewParam(e.currentTarget.value)} />
                <button
                  type="button"
                  class={BTN}
                  disabled={!/^[a-z][a-z0-9_]*$/.test(newParam) || newParam in params}
                  onClick={() => {
                    set({ params: { ...params, [newParam]: 0 } });
                    setNewParam('');
                  }}
                >
                  Add parameter
                </button>
              </div>
            ) : null}
          </div>
        </fieldset>
        <fieldset class="border border-line p-2">
          <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Payment and documents</legend>
          <label class="flex items-center gap-2">
            <span class="w-44 shrink-0">Payment (PKR)</span>
            <input
              type="number"
              class={`${INPUT} w-32 font-mono`}
              value={String(dsl.payment_pkr ?? '')}
              disabled={!editable}
              onInput={(e) => {
                const n = e.currentTarget.valueAsNumber;
                if (!Number.isNaN(n)) set({ payment_pkr: n });
              }}
            />
          </label>
          <div class="mt-2 flex flex-wrap items-center gap-3">
            <span class="w-44 shrink-0">Required documents</span>
            {DOC_KINDS.map((d) => (
              <label key={d} class="flex items-center gap-1">
                <input type="checkbox" checked={docs.includes(d)} disabled={!editable} onChange={(e) => set({ required_docs: e.currentTarget.checked ? [...docs, d] : docs.filter((x) => x !== d) })} />
                {humanize(d)}
              </label>
            ))}
          </div>
          {Object.keys(dsl).some((k) => !known.has(k)) ? <p class="mt-2 text-xs text-warning-ink">Unknown top-level keys are kept, and flagged by Validate.</p> : null}
        </fieldset>
      </div>

      <h3 class="text-sm font-semibold uppercase tracking-wide text-ink-muted">Rules ({rules.length})</h3>
      <ol class="flex flex-col gap-2">
        {rules.map((r, i) => {
          const mine = issues.filter((e) => e.path.startsWith(`$.all[${i}]`));
          return (
            <li key={i} class={`border p-2 ${mine.length ? 'border-danger' : 'border-line'}`}>
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-mono text-xs text-ink-subtle">{i + 1}.</span>
                {editable ? <input class={`${INPUT} w-48 font-mono`} aria-label={`Rule ${i + 1} id`} value={r.id ?? ''} onInput={(e) => setRule(i, { id: e.currentTarget.value })} /> : <Mono>{r.id}</Mono>}
                {editable ? (
                  <select class={INPUT} aria-label={`Rule ${i + 1} kind`} value={String(r.hard)} onChange={(e) => setRule(i, { hard: e.currentTarget.value === 'true' })}>
                    <option value="true">hard: must pass</option>
                    <option value="false">soft: priority only</option>
                  </select>
                ) : (
                  <Badge tone={r.hard ? 'bad' : 'neutral'}>{r.hard ? 'hard' : 'soft'}</Badge>
                )}
                {editable ? (
                  <span class="ms-auto flex gap-2 text-xs">
                    <button type="button" class="underline disabled:opacity-40" disabled={i === 0} onClick={() => move(i, -1)}>
                      up
                    </button>
                    <button type="button" class="underline disabled:opacity-40" disabled={i === rules.length - 1} onClick={() => move(i, 1)}>
                      down
                    </button>
                    <button type="button" class="text-danger underline" onClick={() => set({ all: rules.filter((_, j) => j !== i) })}>
                      delete
                    </button>
                  </span>
                ) : null}
              </div>
              <div class="mt-1 grid gap-2 md:grid-cols-2">
                <label class="flex flex-col gap-0.5">
                  <span class="text-xs text-ink-muted">Label (English)</span>
                  {editable ? <input class={INPUT} value={r.label_en ?? ''} onInput={(e) => setRule(i, { label_en: e.currentTarget.value })} /> : <span>{r.label_en}</span>}
                </label>
                <label class="flex flex-col gap-0.5">
                  <span class="text-xs text-ink-muted">Label (Urdu)</span>
                  {editable ? (
                    <input class={INPUT} dir="rtl" lang="ur" value={r.label_ur ?? ''} onInput={(e) => setRule(i, { label_ur: e.currentTarget.value })} />
                  ) : (
                    <span dir="rtl" lang="ur">
                      {r.label_ur}
                    </span>
                  )}
                </label>
              </div>
              <p class="mt-1">
                <span class="text-xs text-ink-muted">Passes when </span>
                <strong class="font-semibold">{words(r.expr, params)}</strong>
              </p>
              {editable ? <ExprEditor expr={r.expr} onChange={(x) => setRule(i, { expr: x })} index={i} /> : null}
              {mine.length > 0 ? (
                <ul class="mt-1 text-danger">
                  {mine.map((e, k) => (
                    <li key={k}>
                      <Mono>{e.path}</Mono> {e.message}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ol>
      {editable ? (
        <button
          type="button"
          class={`${BTN} self-start`}
          onClick={() => set({ all: [...rules, { id: `rule_${rules.length + 1}`, hard: false, label_en: '', label_ur: '', expr: { '==': [{ var: 'identity_verified' }, true] } }] })}
        >
          Add rule
        </button>
      ) : null}
    </div>
  );
}

function ExprEditor({ expr, onChange, index }: { expr: unknown; onChange: (x: unknown) => void; index: number }) {
  const [text, setText] = useState(() => JSON.stringify(expr));
  const [err, setErr] = useState('');
  return (
    <label class="mt-1 flex flex-col gap-0.5">
      <span class="text-xs text-ink-muted">Expression (JSON)</span>
      <input
        class={`${INPUT} font-mono text-xs`}
        dir="ltr"
        spellcheck={false}
        aria-label={`Rule ${index + 1} expression`}
        value={text}
        onInput={(e) => {
          const t = e.currentTarget.value;
          setText(t);
          try {
            onChange(JSON.parse(t));
            setErr('');
          } catch {
            setErr('Not valid JSON yet; the last good expression is kept.');
          }
        }}
      />
      {err ? <span class="text-xs text-warning-ink">{err}</span> : null}
    </label>
  );
}

export function DiffTab({ versionId, isActive }: { versionId: string; isActive: boolean }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/rules/versions/{version_id}/diff', { params: { path: { version_id: versionId } } })), [versionId]);
  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Comparing with the active version…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} />;
  const { changes } = loaded.data;
  if (isActive || changes.length === 0)
    return <ScreenState kind="empty" density="staff" heading="h2" title="No differences" body={isActive ? 'This is the active version.' : 'These rules are identical to the active version.'} />;
  const show = (x: unknown) => (x === undefined || x === null ? '' : typeof x === 'string' ? x : JSON.stringify(x));
  return (
    <div class="overflow-x-auto border border-line">
      <table class="w-full border-collapse text-sm">
        <caption class="sr-only">Changes against the active version</caption>
        <thead>
          <tr>
            <Th>Path</Th>
            <Th>Change</Th>
            <Th>Active</Th>
            <Th>This version</Th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c, i) => (
            <tr key={i}>
              <td class={TD}>
                <Mono>{c.path}</Mono>
              </td>
              <td class={TD}>
                <Badge tone={c.kind === 'removed' ? 'bad' : c.kind === 'added' ? 'good' : 'warn'}>{c.kind}</Badge>
              </td>
              <td class={`${TD} bg-danger-soft font-mono text-xs`}>{show(c.old)}</td>
              <td class={`${TD} bg-primary-soft font-mono text-xs`}>{show(c.new)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DryRun({ versionId, dirty }: { versionId: string; dirty: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(SAMPLE_CASE, null, 2));
  const income = useMemo(() => {
    try {
      return (JSON.parse(text) as { registry?: { verified_income_pkr?: number | null } }).registry?.verified_income_pkr ?? '';
    } catch {
      return '';
    }
  }, [text]);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const [result, setResult] = useState<S['DryRunOut'] | null>(null);

  const setIncome = (n: number) => {
    try {
      const obj = JSON.parse(text) as { registry?: Record<string, unknown> };
      if (obj.registry) obj.registry.verified_income_pkr = n;
      setText(JSON.stringify(obj, null, 2));
    } catch {
      /* the run reports the JSON problem */
    }
  };

  const run = async () => {
    let input: S['DecisionInput'];
    try {
      input = JSON.parse(text) as S['DecisionInput'];
    } catch {
      setResult(null);
      return setFlash({ tone: 'err', text: 'The sample case is not valid JSON.' });
    }
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/rules/versions/{version_id}/dry-run', { params: { path: { version_id: versionId } }, body: { input } }));
    setBusy(false);
    if (res.ok) setResult(res.data);
    else {
      setResult(null);
      setFlash(flashFail(res.failure));
    }
  };

  const r = result?.result;
  return (
    <div class="flex flex-col gap-2">
      <p class="text-xs text-ink-subtle">
        Decides one invented case with the <strong>saved</strong> version{dirty ? ' (you have unsaved edits; save first to test them)' : ''}. Nothing is stored, sent or paid.
      </p>
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2">
          Registry income (PKR)
          <input
            type="number"
            class={`${INPUT} w-28 font-mono`}
            value={String(income)}
            onInput={(e) => {
              const n = e.currentTarget.valueAsNumber;
              if (!Number.isNaN(n)) setIncome(n);
            }}
          />
        </label>
        <button type="button" class={BTN_PRIMARY} disabled={busy} onClick={() => void run()}>
          {busy ? 'Running…' : 'Run dry run'}
        </button>
      </div>
      <details>
        <summary class="cursor-pointer text-xs text-ink-muted">Edit the whole sample case (JSON)</summary>
        <textarea class="mt-1 h-64 w-full rounded-sm border border-line-strong bg-paper p-2 font-mono text-xs" dir="ltr" spellcheck={false} value={text} onInput={(e) => setText(e.currentTarget.value)} aria-label="Sample case JSON" />
      </details>
      <FlashLine flash={flash} />
      {r ? (
        <div class="flex flex-col gap-2 border border-line p-2" aria-live="polite">
          <div class="flex flex-wrap items-center gap-3">
            <span>
              Outcome <Badge tone={r.outcome === 'approved' ? 'good' : r.outcome === 'rejected' ? 'bad' : 'warn'}>{humanize(r.outcome)}</Badge>
            </span>
            <span>
              Route <Badge>{humanize(r.route)}</Badge>
            </span>
            <span>
              P(eligible) <span class="font-mono">{r.p_eligible.toFixed(2)}</span>
            </span>
            <span>
              Payment <span class="font-mono">{r.payment_pkr ?? 'none'}</span>
            </span>
            <span>
              Reasons <span class="font-mono text-xs">{r.reasons.map(humanize).join(', ') || 'none'}</span>
            </span>
          </div>
          <table class="w-full border-collapse text-sm">
            <caption class="sr-only">Rule by rule result</caption>
            <thead>
              <tr>
                <Th>Rule</Th>
                <Th>Kind</Th>
                <Th>Result</Th>
                <Th>Values used</Th>
              </tr>
            </thead>
            <tbody>
              {r.rule_trace.map((t) => (
                <tr key={t.rule_id}>
                  <td class={TD}>
                    {t.label_en ?? t.rule_id}
                    <br />
                    <Mono>{t.rule_id}</Mono>
                  </td>
                  <td class={TD}>{t.hard ? 'hard' : 'soft'}</td>
                  <td class={TD}>
                    <Badge tone={t.result === 'pass' ? 'good' : t.result === 'fail' ? 'bad' : 'warn'}>{t.result}</Badge>
                  </td>
                  <td class={`${TD} font-mono text-xs`}>{JSON.stringify(t.values_used ?? {})}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p class="text-xs text-ink-subtle">{result?.note}</p>
        </div>
      ) : null}
    </div>
  );
}
