import type { JSX } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { SpeechItem } from '../../shared/audio';
import type { ApiFailure } from '../../shared/api/problem';
import type { ConsentOut, ConsentScope } from '../../shared/api/types';
import type { Speech } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { CrossedPictogram, Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { acting } from '../../shared/acting';
import { lang, t, type Key, type MessageKey } from '../../shared/i18n';
import '../../shared/i18n/more';
import { lazyRoute } from '../../shared/routing';
import { Redirect } from '../../shared/routing';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure, Notice, sayKey } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { CitizenNotFoundPage } from '../NotFound';
import { consents, doneNotice, effectiveStatus, loadConsents, narrowConsent, shareAgain, withdrawConsent } from './api';
import { ConsentCard, knownScopes, SCOPE_ICON, scopeKey, ScopeChips } from './parts';

// The access log, corrections, export, erasure and helpers: a second lazy chunk, so consents load first.
const MoreData = lazyRoute<{ parts: readonly string[] }>(() => import('./MoreData'));

const MORE_LINKS: ReadonlyArray<{ path: string; icon: PictogramName; label: Key; ownOnly: boolean }> = [
  { path: 'access', icon: 'lock', label: 'mydata_open_access', ownOnly: false },
  { path: 'fix', icon: 'edit', label: 'mydata_open_fix', ownOnly: false },
  { path: 'download', icon: 'document', label: 'mydata_open_download', ownOnly: false },
  { path: 'requests', icon: 'clock', label: 'mydata_open_requests', ownOnly: false },
  { path: 'helpers', icon: 'person-help', label: 'mydata_open_helpers', ownOnly: true },
  { path: 'delete', icon: 'delete', label: 'mydata_open_delete', ownOnly: true },
];

/** The rest of "My information": who looked, fix, download, requests, helpers, delete. */
function MoreSection() {
  const { route } = useLocation();
  // Choosing helpers and deleting are the person's own; a helper acting for a family never sees them.
  const links = MORE_LINKS.filter((link) => !(link.ownOnly && acting.value !== null));
  return (
    <section aria-labelledby="mydata-more" class="flex flex-col gap-3">
      <h2 id="mydata-more" class="text-lg font-semibold text-ink-muted">
        {t('mydata_more')}
      </h2>
      {links.map((link) => (
        <button
          key={link.path}
          type="button"
          onClick={() => route(`/my-data/${link.path}`)}
          class="flex min-h-tap-lg items-center gap-3 rounded-lg border-2 border-line-strong bg-paper px-3 py-2 text-start text-xl font-semibold hover:bg-surface"
        >
          <Pictogram name={link.icon} size={40} class={link.path === 'delete' ? 'text-danger' : 'text-primary'} />
          <span class="flex-1">{t(link.label)}</span>
          <Pictogram name="forward" size={28} class="text-ink-muted" />
        </button>
      ))}
    </section>
  );
}

type Loaded = { state: 'loading' } | { state: 'failed'; failure: ApiFailure } | { state: 'ready'; list: ConsentOut[] };

/**
 * The consents, read from the server on every visit (a change made a moment
 * ago is already in memory, so it shows while the fresh list loads).
 */
function useConsents(): { loaded: Loaded; reload: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  useEffect(() => {
    let live = true;
    setFailure(null);
    void loadConsents().then((result) => {
      if (live && !result.ok) setFailure(result.failure);
    });
    return () => {
      live = false;
    };
  }, [attempt]);
  const list = consents.value;
  const reload = (): void => setAttempt((n) => n + 1);
  if (list) return { loaded: { state: 'ready', list }, reload };
  if (failure) return { loaded: { state: 'failed', failure }, reload };
  return { loaded: { state: 'loading' }, reload };
}

function speechOf(keys: readonly MessageKey[], id: string): Speech {
  const code = lang.value;
  const items: SpeechItem[] = keys.map((key) => ({ key, text: t(key, undefined, code) }));
  return { id: `${id}:${code}`, items, lang: code };
}

/** /my-data: who has my information, for what, which kinds, until when; share less, take it back, share again. */
function MyDataList() {
  const { route } = useLocation();
  const { loaded, reload } = useConsents();
  const headingRef = useFocusOnMount<HTMLHeadingElement>(loaded.state === 'ready');
  const notice = doneNotice.value;

  // Say "done" once, then forget it.
  useEffect(() => {
    if (!notice) return undefined;
    sayKey(notice);
    return () => {
      doneNotice.value = null;
    };
  }, [notice]);

  if (loaded.state !== 'ready') {
    return (
      <CitizenShell onBack={() => route('/')}>
        {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={reload} /> : <ScreenState kind="loading" />}
      </CitizenShell>
    );
  }
  const active = loaded.list.filter((item) => effectiveStatus(item) === 'active');
  const activePurposes = new Set(active.map((item) => item.purpose));
  const past = loaded.list.filter((item) => effectiveStatus(item) !== 'active');
  // Offer "share again" once per purpose, on the latest consent that ended.
  const againFor = new Set<string>();
  for (const item of past) {
    if (!activePurposes.has(item.purpose) && !againFor.has(item.purpose)) againFor.add(item.id);
  }

  return (
    <CitizenShell onBack={() => route('/')} prompt={notice ? undefined : 'mydata_prompt'}>
      <div class="flex items-center gap-4">
        <Pictogram name="lock" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('mydata_title')}
        </h1>
      </div>
      {notice ? <Notice tone="ok" icon="yes" text={t(notice)} /> : <p class="text-lg text-ink-muted">{t('mydata_prompt')}</p>}

      {loaded.list.length === 0 ? (
        <ScreenState kind="empty" heading="h2" title={t('mydata_empty_title')} body={t('mydata_empty_body')}>
          <Button size="lg" icon="document" block onClick={() => route('/apply')}>
            {t('home_apply')}
          </Button>
        </ScreenState>
      ) : null}

      {active.map((consent) => (
        <ConsentCard key={consent.id} consent={consent}>
          <div class="grid grid-cols-1 gap-2">
            {knownScopes(consent).length > 1 ? (
              <Button size="md" variant="secondary" icon="less" block onClick={() => route(`/my-data/${consent.id}/less`)}>
                {t('mydata_less')}
              </Button>
            ) : null}
            <Button size="md" variant="neutral" icon="pause" block onClick={() => route(`/my-data/${consent.id}/stop`)}>
              {t('mydata_stop')}
            </Button>
          </div>
        </ConsentCard>
      ))}

      {past.length > 0 ? (
        <section aria-labelledby="mydata-past" class="flex flex-col gap-3">
          <h2 id="mydata-past" class="text-lg font-semibold text-ink-muted">
            {t('mydata_past')}
          </h2>
          {past.map((consent) => (
            <ConsentCard key={consent.id} consent={consent}>
              {againFor.has(consent.id) ? (
                <Button size="lg" icon="retry" block onClick={() => route(`/my-data/${consent.id}/again`)}>
                  {t('mydata_again')}
                </Button>
              ) : null}
            </ConsentCard>
          ))}
        </section>
      ) : null}

      <MoreSection />

      <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')} class="mt-auto">
        {t('go_home')}
      </Button>
    </CitizenShell>
  );
}

/** A consent screen that needs one consent: loading, missing and failed states first. */
function WithConsent({ id, children }: { id: string; children: (consent: ConsentOut) => JSX.Element }) {
  const { route } = useLocation();
  const { loaded, reload } = useConsents();
  if (loaded.state === 'ready') {
    const consent = loaded.list.find((item) => item.id === id);
    if (consent) return children(consent);
    return <CitizenNotFoundPage />;
  }
  return (
    <CitizenShell onBack={() => route('/my-data')}>
      {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={reload} /> : <ScreenState kind="loading" />}
    </CitizenShell>
  );
}

/** Share less: tap a picture to stop sharing it, then confirm. Only removing is possible here. */
function LessScreen({ consent }: { consent: ConsentOut }) {
  const { route } = useLocation();
  const current = knownScopes(consent);
  const [keep, setKeep] = useState<ReadonlySet<ConsentScope>>(new Set(current));
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<MessageKey | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const removed = current.filter((scope) => !keep.has(scope));
  const kept = current.filter((scope) => keep.has(scope));

  if (effectiveStatus(consent) !== 'active') return <Redirect to="/my-data" />;

  const toggle = (scope: ConsentScope): void => {
    setProblem(null);
    const next = new Set(keep);
    if (next.has(scope)) next.delete(scope);
    else next.add(scope);
    setKeep(next);
    sayKey(next.has(scope) ? 'mydata_shared' : 'mydata_not_shared');
  };
  const save = (): void => {
    const why: MessageKey | null = removed.length === 0 ? 'mydata_less_nothing' : kept.length === 0 ? 'mydata_less_all' : null;
    if (why) {
      setProblem(why);
      sayKey(why);
      return;
    }
    setConfirming(true);
  };
  const confirm = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await narrowConsent(consent.id, kept);
    setBusy(false);
    if (!result.ok) {
      setFailure(result.failure);
      return;
    }
    doneNotice.value = 'mydata_less_done';
    route('/my-data', true);
  };

  if (confirming) {
    return (
      <CitizenShell
        onBack={busy ? undefined : () => setConfirming(false)}
        speech={speechOf(['mydata_less_confirm', ...removed.map(scopeKey), 'mydata_less_confirm_body'], `less-confirm:${removed.join(',')}`)}
      >
        <div class="flex items-center gap-4">
          <Pictogram name="less" size={56} class="text-warning-ink" />
          <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
            {t('mydata_less_confirm')}
          </h1>
        </div>
        <ScopeChips scopes={removed} crossed />
        <p class="text-lg text-ink">{t('mydata_less_confirm_body')}</p>
        {failure ? <InlineFailure failure={failure} /> : null}
        <div class="mt-auto flex flex-col gap-3">
          <Button size="lg" icon="yes" block busy={busy} onClick={() => void confirm()}>
            {t('mydata_less_yes')}
          </Button>
          <Button size="lg" variant="neutral" icon="no" block disabled={busy} onClick={() => route('/my-data')}>
            {t('mydata_keep')}
          </Button>
        </div>
      </CitizenShell>
    );
  }

  return (
    <CitizenShell onBack={() => route('/my-data')} prompt="mydata_less_prompt">
      <div class="flex items-center gap-4">
        <Pictogram name="less" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('mydata_less')}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t('mydata_less_prompt')}</p>
      <div class="flex flex-col gap-3" role="group" aria-label={t('mydata_what')}>
        {current.map((scope) => {
          const on = keep.has(scope);
          return (
            <button
              key={scope}
              type="button"
              role="switch"
              aria-checked={on}
              onClick={() => toggle(scope)}
              class={
                'flex min-h-tap-lg w-full items-center gap-3 rounded-lg border-2 px-3 py-2 text-start ' +
                (on ? 'border-primary bg-primary-soft text-primary-strong' : 'border-line-strong bg-surface text-ink')
              }
            >
              {on ? (
                <Pictogram name={SCOPE_ICON[scope]} size={48} />
              ) : (
                <CrossedPictogram name={SCOPE_ICON[scope]} size={48} class="text-ink-muted" />
              )}
              <span class="flex min-w-0 flex-1 flex-col">
                <span class="text-xl font-semibold">{t(scopeKey(scope))}</span>
                <span class="text-base">{t(on ? 'mydata_shared' : 'mydata_not_shared')}</span>
              </span>
              <Pictogram name={on ? 'yes' : 'no'} size={36} class={on ? 'text-primary' : 'text-ink-muted'} />
            </button>
          );
        })}
      </div>
      {problem ? (
        <Notice tone="warn" icon="warning" text={t(problem)}>
          {problem === 'mydata_less_all' ? (
            <Button size="md" variant="neutral" icon="pause" onClick={() => route(`/my-data/${consent.id}/stop`)}>
              {t('mydata_stop')}
            </Button>
          ) : null}
        </Notice>
      ) : null}
      <Button size="lg" icon="yes" block onClick={save} class="mt-auto">
        {t('mydata_save')}
      </Button>
    </CitizenShell>
  );
}

const STOP_ROWS: ReadonlyArray<{ icon: PictogramName; key: MessageKey }> = [
  { icon: 'pause', key: 'mydata_stop_pause' },
  { icon: 'lock', key: 'mydata_stop_officers' },
  { icon: 'retry', key: 'mydata_stop_again' },
];

/** Take it back: say first what happens (applications pause, officers lose access at once), then confirm. */
function StopScreen({ consent }: { consent: ConsentOut }) {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  if (effectiveStatus(consent) !== 'active') return <Redirect to="/my-data" />;

  const confirm = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await withdrawConsent(consent.id);
    setBusy(false);
    if (!result.ok) {
      setFailure(result.failure);
      return;
    }
    doneNotice.value = 'mydata_stop_done';
    route('/my-data', true);
  };
  return (
    <CitizenShell
      onBack={busy ? undefined : () => route('/my-data')}
      speech={speechOf(['mydata_stop_title', 'mydata_stop_prompt', ...STOP_ROWS.map((row) => row.key)], 'stop')}
    >
      <div class="flex items-center gap-4">
        <Pictogram name="pause" size={56} class="text-danger" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('mydata_stop_title')}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t('mydata_stop_prompt')}</p>
      <ul class="flex flex-col gap-3">
        {STOP_ROWS.map((row) => (
          <li key={row.key} class="flex items-start gap-3 rounded-lg border-2 border-line bg-surface p-3">
            <Pictogram name={row.icon} size={48} class="text-ink" />
            <p class="flex-1 text-lg text-ink">{t(row.key)}</p>
          </li>
        ))}
      </ul>
      {failure ? <InlineFailure failure={failure} /> : null}
      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" variant="danger" icon="pause" block busy={busy} onClick={() => void confirm()}>
          {t('mydata_stop_yes')}
        </Button>
        <Button size="lg" variant="secondary" icon="yes" block disabled={busy} onClick={() => route('/my-data')}>
          {t('mydata_stop_no')}
        </Button>
      </div>
    </CitizenShell>
  );
}

/** Share again: the same kinds of data as before; paused applications carry on. */
function AgainScreen({ consent }: { consent: ConsentOut }) {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const scopes = knownScopes(consent);
  const confirm = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await shareAgain(consent);
    setBusy(false);
    if (!result.ok && !(result.failure.kind === 'conflict' && result.failure.problem?.code === 'consent_exists')) {
      setFailure(result.failure);
      return;
    }
    doneNotice.value = 'mydata_again_done';
    route('/my-data', true);
  };
  return (
    <CitizenShell
      onBack={busy ? undefined : () => route('/my-data')}
      speech={speechOf(['mydata_again_title', 'mydata_again_prompt', ...scopes.map(scopeKey)], `again:${scopes.join(',')}`)}
    >
      <div class="flex items-center gap-4">
        <Pictogram name="retry" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('mydata_again_title')}
        </h1>
      </div>
      <p class="text-lg text-ink">{t('mydata_again_prompt')}</p>
      <ScopeChips scopes={scopes} />
      {failure ? <InlineFailure failure={failure} /> : null}
      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" icon="yes" block busy={busy} onClick={() => void confirm()}>
          {t('mydata_again_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block disabled={busy} onClick={() => route('/my-data')}>
          {t('mydata_again_no')}
        </Button>
      </div>
    </CitizenShell>
  );
}

/** /my-data and /my-data/{id}/less | stop | again. A lazy chunk. */
export default function MyDataPages({ parts }: { parts: readonly string[] }) {
  const [id, action, ...extra] = parts;
  if (id === undefined) return <MyDataList />;
  if (id === 'access' || id === 'fix' || id === 'download' || id === 'requests' || id === 'helpers' || id === 'delete') {
    return <MoreData parts={parts} />;
  }
  if (extra.length > 0 || !/^[0-9a-f-]{36}$/i.test(id)) return <CitizenNotFoundPage />;
  switch (action) {
    case 'less':
      return <WithConsent id={id}>{(consent) => <LessScreen key={consent.id} consent={consent} />}</WithConsent>;
    case 'stop':
      return <WithConsent id={id}>{(consent) => <StopScreen key={consent.id} consent={consent} />}</WithConsent>;
    case 'again':
      return <WithConsent id={id}>{(consent) => <AgainScreen key={consent.id} consent={consent} />}</WithConsent>;
    default:
      return <CitizenNotFoundPage />;
  }
}
