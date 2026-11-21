import { useEffect, useState } from 'preact/hooks';
import { session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, failureCode, flashFail, FlashLine, LoadMore, ReasonAction, usePaged, type Flash } from '../kit';
import { Badge, fmtTime, humanize, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';
import { DiffTab, DryRun, IssueList, RuleForm, type Dsl, type Issue } from './RuleParts';

type S = components['schemas'];
type Version = S['RuleVersionOut'];
type Tab = 'form' | 'json' | 'diff' | 'dryrun';
type Ask = '' | 'approval' | 'publish' | 'reject' | 'rollback';
type Outcome = { ok: true; text: string; select?: string } | { ok: false; flash: Flash };

const STATUS_TONE = { draft: 'neutral', pending_approval: 'warn', published: 'good', retired: 'neutral' } as const;
const tone = (status: string) => STATUS_TONE[status as keyof typeof STATUS_TONE] ?? 'neutral';
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const short = (id: string | null | undefined): string => (id ? id.slice(0, 8) : 'n/a');

/** Rule editor for admins: versions, readable form, JSON, validation, dry run, diff and four-eyes publishing. */
export function RulesPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [sets, reloadSets] = useLoad(() => call(api.GET('/v1/rules/sets')), []);
  const [setId, setSetId] = useState('');
  const [selected, setSelected] = useState('');

  useEffect(() => {
    if (sets.state === 'ok' && !setId && sets.data[0]) setSetId(sets.data[0].id);
  }, [sets, setId]);

  const versions = usePaged<Version>(
    (cursor) => (setId ? call(api.GET('/v1/rules/versions', { params: { query: { rule_set_id: setId, limit: 20, ...(cursor ? { cursor: Number(cursor) } : {}) } } })) : Promise.resolve({ ok: true as const, data: { items: [] as Version[] } })),
    [setId],
  );
  useEffect(() => {
    if (!selected && versions.items[0]) setSelected(versions.items[0].id);
  }, [versions.items, selected]);

  const [notice, setNotice] = useState<Flash>(null);
  const refresh = (select?: string, text?: string) => {
    versions.reload();
    reloadSets();
    if (select) setSelected(select);
    setNotice(text ? { tone: 'ok', text } : null);
  };
  const activeSet = sets.state === 'ok' ? sets.data.find((s) => s.id === setId) : undefined;

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Rules
        </h1>
        {sets.state === 'ok' && sets.data.length > 1 ? (
          <label class="flex items-center gap-1">
            Rule set
            <select
              class={INPUT}
              value={setId}
              onChange={(e) => {
                setSetId(e.currentTarget.value);
                setSelected('');
              }}
            >
              {sets.data.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {activeSet ? (
          <span class="text-xs text-ink-muted">
            {activeSet.name}: active version <Badge tone="good">v{activeSet.active_version_no ?? 'none'}</Badge>. A published version applies to the next decision.
          </span>
        ) : null}
        <button type="button" class={`${BTN} ms-auto`} onClick={() => refresh()}>
          Refresh
        </button>
      </div>

      {sets.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading rule sets…" /> : null}
      {sets.state === 'fail' ? <FailureState failure={sets.failure} density="staff" heading="h2" onRetry={reloadSets} /> : null}
      {sets.state === 'ok' && sets.data.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No rule sets" body="This department has no program with rules yet." /> : null}

      {setId ? (
        <>
          {versions.status === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading versions…" /> : null}
          {versions.status === 'fail' && versions.failure ? <FailureState failure={versions.failure} density="staff" heading="h2" onRetry={versions.reload} /> : null}
          {versions.status === 'ok' && versions.items.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No versions" body="This rule set has no versions." /> : null}
          {versions.items.length > 0 ? (
            <div class="max-h-64 overflow-auto border border-line">
              <table class="w-full border-collapse text-sm">
                <caption class="sr-only">Rule versions, newest first. Select one to open it below.</caption>
                <thead>
                  <tr>
                    <Th>Version</Th>
                    <Th>Status</Th>
                    <Th>Valid</Th>
                    <Th>Author</Th>
                    <Th>Published by</Th>
                    <Th>Created</Th>
                    <Th>Published</Th>
                    <Th>Description</Th>
                  </tr>
                </thead>
                <tbody>
                  {versions.items.map((v) => (
                    <tr key={v.id} aria-selected={v.id === selected} class={v.id === selected ? 'bg-info-soft' : 'hover:bg-sunken'}>
                      <td class={TD}>
                        <button type="button" class="font-semibold underline" onClick={() => { setSelected(v.id); setNotice(null); }} aria-current={v.id === selected}>
                          v{v.version_no}
                        </button>{' '}
                        {v.is_active ? <Badge tone="good">active</Badge> : null}
                      </td>
                      <td class={TD}>
                        <Badge tone={tone(v.status)}>{humanize(v.status)}</Badge>
                      </td>
                      <td class={TD}>{v.valid ? 'yes' : <Badge tone="bad">{(v.errors ?? []).length} errors</Badge>}</td>
                      <td class={TD}>
                        <Mono>{short(v.created_by)}</Mono>
                      </td>
                      <td class={TD}>
                        <Mono>{short(v.approved_by)}</Mono>
                      </td>
                      <td class={`${TD} font-mono text-xs`}>{fmtTime(v.created_at)}</td>
                      <td class={`${TD} font-mono text-xs`}>{v.published_at ? fmtTime(v.published_at) : 'n/a'}</td>
                      <td class={TD}>{v.description_en ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <LoadMore next={versions.next} busy={versions.loadingMore} onMore={versions.more} />
        </>
      ) : null}

      <FlashLine flash={notice} />
      {selected ? <VersionPanel key={selected} versionId={selected} onChanged={refresh} /> : null}
    </section>
  );
}

function VersionPanel({ versionId, onChanged }: { versionId: string; onChanged: (select?: string, text?: string) => void }) {
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/rules/versions/{version_id}', { params: { path: { version_id: versionId } } })), [versionId]);
  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the version…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" heading="h2" onRetry={reload} />;
  return <VersionBody v={loaded.data} reload={reload} onChanged={onChanged} />;
}

function VersionBody({ v, reload, onChanged }: { v: Version; reload: () => void; onChanged: (select?: string, text?: string) => void }) {
  const me = session.value.status === 'signed-in' ? session.value.user.id : '';
  const editable = v.status === 'draft';
  const [tab, setTab] = useState<Tab>('form');
  const [dsl, setDsl] = useState<Dsl>(() => clone(v.dsl));
  const [descEn, setDescEn] = useState(v.description_en ?? '');
  const [jsonText, setJsonText] = useState(() => JSON.stringify(v.dsl, null, 2));
  const [jsonErr, setJsonErr] = useState('');
  const [issues, setIssues] = useState<Issue[] | null>(v.valid ? null : (v.errors ?? []));
  const [validNote, setValidNote] = useState('');
  const [flash, setFlash] = useState<Flash>(null);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<Ask>('');
  const dirty = editable && (JSON.stringify(dsl) !== JSON.stringify(v.dsl) || descEn !== (v.description_en ?? ''));

  const setDslObj = (next: Dsl) => {
    setDsl(next);
    setJsonText(JSON.stringify(next, null, 2));
    setJsonErr('');
    setValidNote('');
  };
  const onJson = (text: string) => {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as unknown;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('The rules must be a JSON object.');
      setDsl(parsed as Dsl);
      setJsonErr('');
      setValidNote('');
    } catch (e) {
      setJsonErr(e instanceof Error ? e.message : 'Not valid JSON.');
    }
  };

  const act = async (run: () => Promise<Outcome>) => {
    setBusy(true);
    setFlash(null);
    const out = await run();
    setBusy(false);
    if (out.ok) {
      setAsk('');
      onChanged(out.select, out.text);
      reload();
    } else setFlash(out.flash);
  };

  const validate = async () => {
    setBusy(true);
    const res = await call(api.POST('/v1/rules/validate', { body: { dsl } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash(null);
    setIssues(res.data.valid ? null : (res.data.errors ?? []));
    setValidNote(res.data.valid ? 'Valid: every rule passed the checks.' : '');
  };

  const save = () =>
    act(async () => {
      const res = await call(api.PATCH('/v1/rules/versions/{version_id}', { params: { path: { version_id: v.id } }, body: { dsl, description_en: descEn || null } }));
      return res.ok ? { ok: true, text: `Draft v${v.version_no} saved.` } : { ok: false, flash: flashFail(res.failure) };
    });

  const newDraft = () =>
    act(async () => {
      const res = await call(api.POST('/v1/rules/versions', { body: { parent_version_id: v.id } }));
      return res.ok ? { ok: true, text: `Draft v${res.data.version_no} created from v${v.version_no}.`, select: res.data.id } : { ok: false, flash: flashFail(res.failure) };
    });

  const workflow = (kind: Exclude<Ask, ''>, reason: string) =>
    act(async (): Promise<Outcome> => {
      const params = { path: { version_id: v.id } };
      const body = { reason };
      if (kind === 'approval') {
        const res = await call(api.POST('/v1/rules/versions/{version_id}/request-approval', { params, body }));
        return res.ok ? { ok: true, text: `v${v.version_no} is frozen and waits for a second admin.` } : { ok: false, flash: flashFail(res.failure) };
      }
      if (kind === 'publish') {
        const res = await call(api.POST('/v1/rules/versions/{version_id}/publish', { params, body }));
        if (res.ok) return { ok: true, text: `v${v.version_no} is published and active. The next decision uses it.` };
        const f = flashFail(res.failure);
        if (f && failureCode(res.failure) === 'four_eyes_required') f.text = `Refused: you wrote this change, so you cannot publish it. A different admin must publish it. (${f.text})`;
        return { ok: false, flash: f };
      }
      if (kind === 'reject') {
        const res = await call(api.POST('/v1/rules/versions/{version_id}/reject', { params, body }));
        return res.ok ? { ok: true, text: `v${v.version_no} was sent back to draft.` } : { ok: false, flash: flashFail(res.failure) };
      }
      const res = await call(api.POST('/v1/rules/versions/{version_id}/rollback', { params, body }));
      return res.ok ? { ok: true, text: `Rollback created v${res.data.version_no}. It needs a second admin to publish.`, select: res.data.id } : { ok: false, flash: flashFail(res.failure) };
    });

  const wrote = !!me && v.created_by === me;
  const tabs: [Tab, string][] = [
    ['form', 'Form'],
    ['json', 'JSON'],
    ['diff', 'Diff vs active'],
    ['dryrun', 'Dry run'],
  ];
  const toggle = (k: Exclude<Ask, ''>) => setAsk(ask === k ? '' : k);

  return (
    <Section
      id="version-title"
      title={`Version ${v.version_no}`}
      aside={
        <span class="flex items-center gap-2 text-xs">
          <Badge tone={tone(v.status)}>{humanize(v.status)}</Badge>
          {v.is_active ? <Badge tone="good">active</Badge> : null}
          {wrote ? <Badge tone="info">you wrote this</Badge> : null}
          <Mono title="content hash">{v.content_hash?.slice(0, 12) ?? ''}</Mono>
        </span>
      }
    >
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Actions for this version">
          {editable ? (
            <>
              <button type="button" class={BTN} disabled={busy || !!jsonErr} onClick={() => void validate()}>
                Validate
              </button>
              <button type="button" class={BTN_PRIMARY} disabled={busy || !dirty || !!jsonErr} onClick={() => void save()}>
                Save draft
              </button>
              <button type="button" class={BTN} disabled={busy || dirty || !v.valid} onClick={() => toggle('approval')} title={dirty ? 'Save the draft first' : !v.valid ? 'The saved draft is not valid' : ''}>
                Request approval
              </button>
            </>
          ) : null}
          {v.status === 'pending_approval' ? (
            <>
              <button type="button" class={BTN_PRIMARY} disabled={busy} onClick={() => toggle('publish')}>
                Publish (second admin)
              </button>
              <button type="button" class={BTN} disabled={busy} onClick={() => toggle('reject')}>
                Send back
              </button>
            </>
          ) : null}
          <button type="button" class={BTN} disabled={busy} onClick={() => void newDraft()}>
            New draft from this version
          </button>
          {(v.status === 'published' || v.status === 'retired') && !v.is_active ? (
            <button type="button" class={BTN} disabled={busy} onClick={() => toggle('rollback')}>
              Roll back to this version
            </button>
          ) : null}
        </div>

        {ask === 'approval' ? <ReasonAction label="Request approval" tone="primary" busy={busy} help="Freezes the draft and asks a second admin. Stored in the audit log." onSubmit={(r) => void workflow('approval', r)} onCancel={() => setAsk('')} /> : null}
        {ask === 'publish' ? <ReasonAction label="Publish now" tone="primary" busy={busy} help="Applies to the next decision. The author cannot do this." onSubmit={(r) => void workflow('publish', r)} onCancel={() => setAsk('')} /> : null}
        {ask === 'reject' ? <ReasonAction label="Send back to draft" tone="danger" busy={busy} onSubmit={(r) => void workflow('reject', r)} onCancel={() => setAsk('')} /> : null}
        {ask === 'rollback' ? <ReasonAction label="Create rollback" busy={busy} help="Creates a new version copying this one; a second admin must publish it." onSubmit={(r) => void workflow('rollback', r)} onCancel={() => setAsk('')} /> : null}

        <FlashLine flash={flash} />
        {validNote ? (
          <p role="status" class="border border-primary bg-primary-soft px-2 py-1 text-sm text-primary-strong">
            {validNote}
          </p>
        ) : null}
        {issues && issues.length > 0 ? <IssueList issues={issues} /> : null}

        {editable ? (
          <label class="flex items-center gap-2">
            <span class="shrink-0">Description</span>
            <input class={`${INPUT} flex-1`} value={descEn} maxLength={2000} onInput={(e) => setDescEn(e.currentTarget.value)} />
          </label>
        ) : v.description_en ? (
          <p class="text-ink-muted">{v.description_en}</p>
        ) : null}

        <div role="tablist" aria-label="View" class="flex gap-1 border-b border-line">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} class={`px-3 py-1 ${tab === key ? 'border-b-2 border-primary font-semibold' : 'text-ink-muted hover:bg-sunken'}`} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {tab === 'form' ? <RuleForm dsl={dsl} editable={editable} issues={issues ?? []} onChange={setDslObj} /> : null}
        {tab === 'json' ? (
          editable ? (
            <div class="flex flex-col gap-1">
              <textarea class="h-96 w-full rounded-sm border border-line-strong bg-paper p-2 font-mono text-xs" spellcheck={false} dir="ltr" value={jsonText} onInput={(e) => onJson(e.currentTarget.value)} aria-label="Rules as JSON" aria-invalid={!!jsonErr} />
              {jsonErr ? (
                <p role="alert" class="text-danger">
                  JSON error: {jsonErr}. The form and Save use the last good text.
                </p>
              ) : (
                <p class="text-xs text-ink-subtle">Rules are data. Only the listed operators exist; nothing here is run as code.</p>
              )}
            </div>
          ) : (
            <pre class="max-h-96 overflow-auto border border-line bg-sunken p-2 font-mono text-xs" dir="ltr">
              {JSON.stringify(v.dsl, null, 2)}
            </pre>
          )
        ) : null}
        {tab === 'diff' ? <DiffTab key={`${v.status}-${v.content_hash}`} versionId={v.id} isActive={v.is_active} /> : null}
        {tab === 'dryrun' ? <DryRun versionId={v.id} dirty={dirty} /> : null}
      </div>
    </Section>
  );
}
