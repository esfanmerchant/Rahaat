import type { ComponentChildren } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { acting } from '../../shared/acting';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { AccessEntry, DataRequestOut, DelegationOut } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { lang, t, type Key } from '../../shared/i18n';
import '../../shared/i18n/more';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { AnswerButton, AnswerGroup, InlineFailure, Notice, sayKey } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { Keypad, PinDots } from '../Keypad';
import { CitizenNotFoundPage } from '../NotFound';
import { PhoneSlots, usePhonePaste } from '../PhoneField';
import { checkPhone, mockPhone, PHONE_LENGTH, PIN_MAX, PIN_MIN } from '../phone';
import { formatDate } from '../result/data';

/** The common frame: back to "My information", a speaker for the prompt, a picture and a title. */
function Page({ icon, title, prompt, children }: { icon: PictogramName; title: Key; prompt?: Key; children?: ComponentChildren }) {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  return (
    <CitizenShell onBack={() => route('/my-data')} prompt={prompt}>
      <div class="flex items-center gap-4">
        <Pictogram name={icon} size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t(title)}
        </h1>
      </div>
      {prompt ? <p class="text-lg text-ink-muted">{t(prompt)}</p> : null}
      {children}
    </CitizenShell>
  );
}

/** Fetch once and again on retry; a failure keeps its kind so the right state shows (offline, denied, error). */
function useLoad<T>(load: () => Promise<{ ok: true; data: T } | { ok: false; failure: ApiFailure }>): {
  data: T | null;
  failure: ApiFailure | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setFailure(null);
    void load().then((result) => {
      if (!live) return;
      if (result.ok) setData(result.data);
      else setFailure(result.failure);
    });
    return () => {
      live = false;
    };
  }, [attempt]);
  return { data, failure, reload: () => setAttempt((n) => n + 1) };
}

// ---- who looked at my information ------------------------------------------------------------------

const EVENT_ICON: Record<AccessEntry['event'], PictogramName> = {
  viewed: 'document',
  denied: 'lock',
  helper_opened: 'person-help',
  helper_acted: 'edit',
  exported: 'document',
};
const EVENT_KEY: Record<AccessEntry['event'], Key> = {
  viewed: 'acc_ev_viewed',
  denied: 'acc_ev_denied',
  helper_opened: 'acc_ev_helper_opened',
  helper_acted: 'acc_ev_helper_acted',
  exported: 'acc_ev_exported',
};
const ROLE_KEY: Record<string, Key> = { officer: 'acc_role_officer', admin: 'acc_role_admin', auditor: 'acc_role_auditor' };
const WHY_KEY: Record<string, Key> = {
  case_review: 'acc_why_case_review',
  helper_assist: 'acc_why_helper_assist',
  audit: 'acc_why_audit',
  partner_api: 'acc_why_partner_api',
  administration: 'acc_why_administration',
  processing: 'acc_why_processing',
};

/** Staff appear by role and department only (the server never sends a staff member's name). */
function whoText(entry: AccessEntry): string {
  switch (entry.actor_kind) {
    case 'staff': {
      const role = entry.actor_role ? ROLE_KEY[entry.actor_role] : undefined;
      return `${t('acc_who_staff', { department: entry.department })}${role ? ` (${t(role)})` : ''}`;
    }
    case 'helper':
      return entry.actor_name ? t('acc_who_helper', { name: entry.actor_name }) : t('acc_who_helper_plain');
    case 'partner':
      return t('acc_who_partner');
    default:
      return t('acc_who_system');
  }
}

function AccessRow({ entry }: { entry: AccessEntry }) {
  const why = entry.event === 'viewed' && entry.reason ? WHY_KEY[entry.reason] : undefined;
  return (
    <li class="flex items-start gap-3 rounded-lg border-2 border-line bg-paper p-3">
      <Pictogram name={EVENT_ICON[entry.event]} size={40} class={entry.allowed ? 'text-primary' : 'text-danger'} />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        {/* Names and departments are server data: text. */}
        <p class="text-lg font-bold" dir="auto">
          {whoText(entry)}
        </p>
        <p class="text-lg text-ink">{t(EVENT_KEY[entry.event])}</p>
        {why ? (
          <p class="text-base text-ink-muted">
            {t('acc_why')}: {t(why)}
          </p>
        ) : null}
        <p class="text-base text-ink-muted">
          <span class="rh-ltr">{formatDate(entry.at, lang.value, true)}</span>
        </p>
        <p class={`text-base font-semibold ${entry.allowed ? 'text-primary-strong' : 'text-danger'}`}>{t(entry.allowed ? 'acc_allowed' : 'acc_refused')}</p>
      </div>
    </li>
  );
}

function AccessLogPage() {
  const [items, setItems] = useState<AccessEntry[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const load = async (cursor: string | null): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await call(api.GET('/v1/me/access-log', { params: { query: { limit: 20, ...(cursor ? { cursor: Number(cursor) } : {}) } } }));
    setBusy(false);
    if (!result.ok) {
      setFailure(result.failure);
      return;
    }
    setItems((old) => (cursor && old ? [...old, ...result.data.items] : result.data.items));
    setNext(result.data.next_cursor ?? null);
  };
  useEffect(() => {
    setItems(null);
    void load(null);
  }, [attempt]);

  return (
    <Page icon="lock" title="mydata_open_access" prompt="acc_prompt">
      {items === null && !failure ? <ScreenState kind="loading" /> : null}
      {failure && items === null ? <FailureState failure={failure} heading="h2" onRetry={() => setAttempt((n) => n + 1)} /> : null}
      {items && items.length === 0 ? <ScreenState kind="empty" heading="h2" title={t('acc_empty_title')} body={t('acc_empty_body')} /> : null}
      {items && items.length > 0 ? (
        <ul class="flex flex-col gap-3">
          {items.map((entry) => (
            <AccessRow key={entry.seq} entry={entry} />
          ))}
        </ul>
      ) : null}
      {items && failure ? <InlineFailure failure={failure} /> : null}
      {next ? (
        <Button size="md" variant="neutral" icon="plus" block busy={busy} onClick={() => void load(next)}>
          {t('acc_more')}
        </Button>
      ) : null}
    </Page>
  );
}

// ---- fix my information ----------------------------------------------------------------------------

type FixField = 'full_name' | 'household_size' | 'income_band' | 'is_widow' | 'has_disability' | 'receives_other_aid';
const FIX_FIELDS: ReadonlyArray<{ field: FixField; icon: PictogramName; label: Key }> = [
  { field: 'full_name', icon: 'person', label: 'fix_field_full_name' },
  { field: 'household_size', icon: 'family', label: 'fix_field_household_size' },
  { field: 'income_band', icon: 'payment', label: 'fix_field_income_band' },
  { field: 'is_widow', icon: 'widow', label: 'fix_field_is_widow' },
  { field: 'has_disability', icon: 'disability', label: 'fix_field_has_disability' },
  { field: 'receives_other_aid', icon: 'payment', label: 'fix_field_receives_other_aid' },
];
const BANDS: ReadonlyArray<{ value: string; icon: PictogramName; label: Key }> = [
  { value: 'under_15k', icon: 'income-1', label: 'income_under_15k' },
  { value: '15k_30k', icon: 'income-2', label: 'income_15k_30k' },
  { value: '30k_50k', icon: 'income-3', label: 'income_30k_50k' },
  { value: 'over_50k', icon: 'income-4', label: 'income_over_50k' },
];
const REASONS: ReadonlyArray<{ key: Key; icon: PictogramName }> = [
  { key: 'fix_why_card', icon: 'card' },
  { key: 'fix_why_changed', icon: 'clock' },
  { key: 'fix_why_mistake', icon: 'edit' },
];

type FixValue = string | number | boolean;

function FixPage() {
  const [field, setField] = useState<FixField | null>(null);
  const [value, setValue] = useState<FixValue | null>(null);
  const [step, setStep] = useState<'field' | 'value' | 'why' | 'done'>('field');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [note, setNote] = useState<Key | null>(null);
  const { route } = useLocation();

  const choose = (next: FixField): void => {
    setField(next);
    setValue(next === 'household_size' ? 1 : null);
    setStep('value');
  };
  const send = async (reason: Key): Promise<void> => {
    if (!field || value === null) return;
    setBusy(true);
    setFailure(null);
    setNote(null);
    const result = await call(api.POST('/v1/me/corrections', { body: { field, new_value: value, reason: t(reason, undefined, 'en') } }));
    setBusy(false);
    if (result.ok) {
      setStep('done');
      sayKey('fix_done_title');
    } else if (result.failure.kind === 'conflict') setNote('fix_exists');
    else if (result.failure.kind === 'not_found') setNote('fix_need_app');
    else setFailure(result.failure);
  };

  if (step === 'done') {
    return (
      <Page icon="yes" title="fix_done_title">
        <p class="text-lg text-ink">{t('fix_done_body')}</p>
        <Button size="lg" icon="clock" block onClick={() => route('/my-data/requests')}>
          {t('mydata_open_requests')}
        </Button>
      </Page>
    );
  }

  if (step === 'field' || !field) {
    return (
      <Page icon="edit" title="mydata_open_fix" prompt="fix_prompt">
        <div class="flex flex-col gap-3">
          {FIX_FIELDS.map((item) => (
            <button
              key={item.field}
              type="button"
              onClick={() => choose(item.field)}
              class="flex min-h-tap-lg items-center gap-3 rounded-lg border-2 border-line-strong bg-paper px-3 py-2 text-start text-xl font-semibold hover:bg-surface"
            >
              <Pictogram name={item.icon} size={48} class="text-primary" />
              <span class="flex-1">{t(item.label)}</span>
              <Pictogram name="forward" size={28} class="text-ink-muted" />
            </button>
          ))}
        </div>
      </Page>
    );
  }

  const spec = FIX_FIELDS.find((item) => item.field === field);
  if (step === 'value') {
    return (
      <Page icon={spec?.icon ?? 'edit'} title={spec?.label ?? 'mydata_open_fix'} prompt="fix_value_prompt">
        {field === 'full_name' ? (
          <label class="flex flex-col gap-1 text-base font-semibold text-ink-muted">
            {t('fix_name_label')}
            <input
              type="text"
              value={typeof value === 'string' ? value : ''}
              maxLength={120}
              autoComplete="off"
              dir="auto"
              onInput={(event) => setValue((event.target as HTMLInputElement).value)}
              class="min-h-tap-lg rounded-lg border-2 border-line-strong bg-paper px-3 text-xl font-normal text-ink"
            />
          </label>
        ) : null}
        {field === 'household_size' ? (
          <div dir="ltr" class="flex items-center justify-between gap-3">
            <button
              type="button"
              aria-label={t('household_less')}
              disabled={Number(value) <= 1}
              onClick={() => setValue(Math.max(1, Number(value) - 1))}
              class="flex size-24 items-center justify-center rounded-full border-2 border-line-strong bg-paper hover:bg-surface disabled:border-line disabled:text-ink-subtle"
            >
              <Pictogram name="minus" size={56} />
            </button>
            <output class="rh-ltr text-center text-[4.5rem] font-bold leading-none">{String(value)}</output>
            <button
              type="button"
              aria-label={t('household_more')}
              disabled={Number(value) >= 20}
              onClick={() => setValue(Math.min(20, Number(value) + 1))}
              class="flex size-24 items-center justify-center rounded-full border-2 border-primary bg-primary text-white hover:bg-primary-strong disabled:border-line disabled:bg-surface disabled:text-ink-subtle"
            >
              <Pictogram name="plus" size={56} />
            </button>
          </div>
        ) : null}
        {field === 'income_band' ? (
          <AnswerGroup>
            {BANDS.map((band) => (
              <AnswerButton key={band.value} icon={band.icon} label={t(band.label)} selected={value === band.value} onSelect={() => setValue(band.value)} />
            ))}
          </AnswerGroup>
        ) : null}
        {field === 'is_widow' || field === 'has_disability' || field === 'receives_other_aid' ? (
          <AnswerGroup>
            <AnswerButton icon="yes" label={t('answer_yes')} selected={value === true} onSelect={() => setValue(true)} />
            <AnswerButton icon="no" label={t('answer_no')} selected={value === false} tone="text-danger" onSelect={() => setValue(false)} />
          </AnswerGroup>
        ) : null}
        <Button
          size="lg"
          icon="forward"
          block
          disabled={value === null || (typeof value === 'string' && value.trim().length < 2)}
          onClick={() => setStep('why')}
          class="mt-auto"
        >
          {t('next')}
        </Button>
        <Button size="md" variant="quiet" icon="back" block onClick={() => setStep('field')}>
          {t('back')}
        </Button>
      </Page>
    );
  }

  return (
    <Page icon="edit" title="mydata_open_fix" prompt="fix_why_prompt">
      <AnswerGroup>
        {REASONS.map((reason) => (
          <AnswerButton key={reason.key} icon={reason.icon} label={t(reason.key)} selected={false} disabled={busy} onSelect={() => void send(reason.key)} />
        ))}
      </AnswerGroup>
      {note ? <Notice tone="check" icon="person-help" text={t(note)} /> : null}
      {failure ? <InlineFailure failure={failure} /> : null}
      <Button size="md" variant="quiet" icon="back" block disabled={busy} onClick={() => setStep('value')}>
        {t('back')}
      </Button>
    </Page>
  );
}

// ---- download my information -----------------------------------------------------------------------

function DownloadPage() {
  const [phase, setPhase] = useState<'idle' | 'busy' | 'done'>('idle');
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const download = async (): Promise<void> => {
    setPhase('busy');
    setFailure(null);
    const result = await call(api.GET('/v1/me/export', { parseAs: 'blob' }));
    if (!result.ok) {
      setPhase('idle');
      setFailure(result.failure);
      return;
    }
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const url = URL.createObjectURL(result.data as Blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `rahat-my-data-${stamp}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    setPhase('done');
    sayKey('dl_done');
  };

  return (
    <Page icon="document" title="mydata_open_download" prompt="dl_prompt">
      {phase === 'done' ? <Notice tone="ok" icon="yes" text={t('dl_done')} /> : null}
      {failure ? <InlineFailure failure={failure} /> : null}
      <Button size="lg" icon="document" block busy={phase === 'busy'} onClick={() => void download()} class="mt-auto">
        {phase === 'busy' ? t('dl_busy') : t('dl_button')}
      </Button>
    </Page>
  );
}

// ---- delete my information -------------------------------------------------------------------------

const WARNINGS: ReadonlyArray<{ key: Key; icon: PictogramName }> = [
  { key: 'del_warn_1', icon: 'person-help' },
  { key: 'del_warn_2', icon: 'delete' },
  { key: 'del_warn_3', icon: 'lock' },
];

function DeletePage() {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Key | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const ask = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await call(api.POST('/v1/me/erasure-request', { body: {} }));
    setBusy(false);
    if (result.ok) setDone('del_done_title');
    else if (result.failure.kind === 'conflict') setDone('del_exists');
    else setFailure(result.failure);
  };
  useEffect(() => {
    if (done) sayKey(done);
  }, [done]);

  if (done) {
    return (
      <Page icon="yes" title={done}>
        {done === 'del_done_title' ? <p class="text-lg text-ink">{t('del_done_body')}</p> : null}
        <Button size="lg" icon="clock" block onClick={() => route('/my-data/requests')}>
          {t('mydata_open_requests')}
        </Button>
      </Page>
    );
  }
  return (
    <Page icon="delete" title="mydata_open_delete">
      <ul class="flex flex-col gap-3">
        {WARNINGS.map((row) => (
          <li key={row.key} class="flex items-start gap-3 rounded-lg border-2 border-line bg-surface p-3">
            <Pictogram name={row.icon} size={48} class="text-ink" />
            <p class="flex-1 text-lg text-ink">{t(row.key)}</p>
          </li>
        ))}
      </ul>
      {failure ? <InlineFailure failure={failure} /> : null}
      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" variant="danger" icon="delete" block busy={busy} onClick={() => void ask()}>
          {t('del_yes')}
        </Button>
        <Button size="lg" variant="secondary" icon="yes" block disabled={busy} onClick={() => route('/my-data')}>
          {t('del_no')}
        </Button>
      </div>
    </Page>
  );
}

// ---- my requests -----------------------------------------------------------------------------------

const REQ_STATUS: Record<string, { key: Key; icon: PictogramName; tone: string }> = {
  open: { key: 'req_open', icon: 'clock', tone: 'border-info bg-info-soft text-info-strong' },
  accepted: { key: 'req_accepted', icon: 'yes', tone: 'border-primary bg-primary-soft text-primary-strong' },
  rejected: { key: 'req_rejected', icon: 'no', tone: 'border-line-strong bg-surface text-ink' },
};

function RequestsPage() {
  const { data, failure, reload } = useLoad<DataRequestOut[]>(() => call(api.GET('/v1/me/data-requests')));
  return (
    <Page icon="clock" title="mydata_open_requests" prompt="req_prompt">
      {data === null && !failure ? <ScreenState kind="loading" /> : null}
      {failure ? <FailureState failure={failure} heading="h2" onRetry={reload} /> : null}
      {data && data.length === 0 ? <ScreenState kind="empty" heading="h2" title={t('req_empty_title')} body={t('req_empty_body')} /> : null}
      {data && data.length > 0 ? (
        <ul class="flex flex-col gap-3">
          {data.map((item) => {
            const status = REQ_STATUS[item.status] ?? REQ_STATUS['open']!;
            const fieldKey = item.field ? (`fix_field_${item.field}` as Key) : null;
            return (
              <li key={item.id} class="flex flex-col gap-2 rounded-lg border-2 border-line-strong bg-paper p-3">
                <p class="flex items-center gap-2 text-xl font-bold">
                  <Pictogram name={item.kind === 'erasure' ? 'delete' : 'edit'} size={36} class="text-primary" />
                  <span>
                    {t(item.kind === 'erasure' ? 'mydata_open_delete' : 'req_kind_correction')}
                    {fieldKey && t(fieldKey) !== fieldKey ? `: ${t(fieldKey)}` : ''}
                  </span>
                </p>
                <span class={`inline-flex w-fit items-center gap-1 rounded-full border-2 px-3 py-1 text-base font-semibold ${status.tone}`}>
                  <Pictogram name={status.icon} size={24} />
                  {t(status.key)}
                </span>
                <p class="text-base text-ink-muted">
                  {t('req_asked')}: {formatDate(item.requested_at, lang.value)}
                </p>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Page>
  );
}

// ---- my helpers ------------------------------------------------------------------------------------

const SCOPE_ICON: Record<string, PictogramName> = { track: 'clock', apply: 'edit', upload: 'camera' };
const SCOPE_KEY: Record<string, Key> = { track: 'home_see_application', apply: 'mh_scope_apply', upload: 'mh_scope_upload' };
const DELEGATION_STATUS: Record<string, { key: Key; tone: string; icon: PictogramName }> = {
  live: { key: 'mh_live', tone: 'border-primary bg-primary-soft text-primary-strong', icon: 'yes' },
  expired: { key: 'mydata_status_expired', tone: 'border-line-strong bg-surface text-ink', icon: 'clock' },
  revoked: { key: 'acc_refused', tone: 'border-line-strong bg-surface text-ink', icon: 'pause' },
};

function HelperCard({ item, onChanged }: { item: DelegationOut; onChanged: () => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const status = DELEGATION_STATUS[item.status] ?? DELEGATION_STATUS['expired']!;
  const stop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await call(api.POST('/v1/me/helpers/{delegation_id}/revoke', { params: { path: { delegation_id: item.id } } }));
    setBusy(false);
    if (result.ok) {
      sayKey('mh_stop_done');
      onChanged();
    } else setFailure(result.failure);
  };
  return (
    <li class="flex flex-col gap-3 rounded-lg border-2 border-line-strong bg-paper p-3">
      <div class="flex items-center gap-3">
        <Pictogram name="person-help" size={48} class="text-primary" />
        <div class="flex min-w-0 flex-1 flex-col">
          <p class="text-xl font-bold" dir="auto">
            {item.helper_name}
          </p>
          {item.helper_phone_masked ? <p class="rh-ltr text-base text-ink-muted">{item.helper_phone_masked}</p> : null}
        </div>
      </div>
      <ul class="flex flex-wrap gap-2">
        {item.scopes.map((scope) => (
          <li key={scope} class="inline-flex items-center gap-1 rounded-full border-2 border-line px-2 py-1 text-base">
            <Pictogram name={SCOPE_ICON[scope] ?? 'document'} size={24} />
            {SCOPE_KEY[scope] ? t(SCOPE_KEY[scope]) : scope}
          </li>
        ))}
      </ul>
      <div class="flex flex-wrap items-center gap-2">
        <span class={`inline-flex items-center gap-1 rounded-full border-2 px-3 py-1 text-base font-semibold ${status.tone}`}>
          <Pictogram name={status.icon} size={24} />
          {t(status.key)}
        </span>
        {item.status === 'live' ? (
          <span class="text-base text-ink-muted">
            {t('mydata_until')}: {formatDate(item.expires_at, lang.value)}
          </span>
        ) : null}
      </div>
      {failure ? <InlineFailure failure={failure} /> : null}
      {item.status === 'live' ? (
        asking ? (
          <div role="alert" class="flex flex-col gap-2 rounded-lg border-2 border-danger bg-danger-soft p-3">
            <p class="text-lg font-semibold text-ink">{t('mh_stop_ask')}</p>
            <Button size="md" variant="danger" icon="pause" block busy={busy} onClick={() => void stop()}>
              {t('mh_stop_yes')}
            </Button>
            <Button size="md" variant="neutral" icon="yes" block disabled={busy} onClick={() => setAsking(false)}>
              {t('mh_stop_no')}
            </Button>
          </div>
        ) : (
          <Button size="md" variant="neutral" icon="pause" block onClick={() => setAsking(true)}>
            {t('mh_stop')}
          </Button>
        )
      ) : null}
    </li>
  );
}

function HelpersPage() {
  const { route } = useLocation();
  const { data, failure, reload } = useLoad<DelegationOut[]>(() => call(api.GET('/v1/me/helpers')));
  return (
    <Page icon="person-help" title="mydata_open_helpers" prompt="mh_prompt">
      {data === null && !failure ? <ScreenState kind="loading" /> : null}
      {failure ? <FailureState failure={failure} heading="h2" onRetry={reload} /> : null}
      {data && data.length === 0 ? <ScreenState kind="empty" heading="h2" title={t('mh_empty_title')} body={t('mh_empty_body')} /> : null}
      {data && data.length > 0 ? (
        <ul class="flex flex-col gap-3">
          {[...data].sort((a, b) => Number(b.status === 'live') - Number(a.status === 'live')).map((item) => (
            <HelperCard key={item.id} item={item} onChanged={reload} />
          ))}
        </ul>
      ) : null}
      {data ? (
        <Button size="lg" icon="plus" block onClick={() => route('/my-data/helpers/new')} class="mt-auto">
          {t('mh_add')}
        </Button>
      ) : null}
    </Page>
  );
}

const SCOPES = ['track', 'apply', 'upload'] as const;
type Scope = (typeof SCOPES)[number];

/** Choose a helper: phone, what they may do, a PIN (twice, so a slip is caught), then save. */
function NewHelperPage() {
  const { route } = useLocation();
  const [step, setStep] = useState<'phone' | 'scopes' | 'pin' | 'again'>('phone');
  const [local, setLocal] = useState('');
  const [scopes, setScopes] = useState<ReadonlySet<Scope>>(new Set(['track']));
  const [pin, setPin] = useState('');
  const [first, setFirst] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Key | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const digit = useCallback(
    (d: string) => {
      if (step === 'phone') setLocal((v) => (v.length < PHONE_LENGTH ? v + d : v));
      else setPin((v) => (v.length < PIN_MAX ? v + d : v));
    },
    [step],
  );
  usePhonePaste(
    useCallback((digits: string) => {
      setNote(null);
      setLocal(digits);
    }, []),
    step === 'phone' && !busy,
  );
  const del = useCallback(() => (step === 'phone' ? setLocal((v) => v.slice(0, -1)) : setPin((v) => v.slice(0, -1))), [step]);

  const save = async (secret: string): Promise<void> => {
    setBusy(true);
    setFailure(null);
    setNote(null);
    const result = await call(
      api.POST('/v1/me/helpers', { body: { helper_phone: mockPhone(local), scopes: [...scopes], expires_in_days: 90, pin: secret } }),
    );
    setBusy(false);
    if (result.ok) {
      sayKey('mh_done');
      route('/my-data/helpers', true);
      return;
    }
    if (result.failure.kind === 'not_found') {
      setNote('mh_not_found');
      setStep('phone');
    } else if (result.failure.kind === 'conflict') setNote('mh_exists');
    else setFailure(result.failure);
    setPin('');
  };

  const onDone = (): void => {
    if (step === 'phone') {
      const check = checkPhone(local);
      if (check === 'ok') {
        setNote(null);
        setStep('scopes');
      } else {
        const key = check === 'not_mock' ? 'phone_not_mock' : 'login_phone_invalid';
        setNote(key);
        sayKey(key);
      }
    } else if (step === 'pin') {
      if (pin.length >= PIN_MIN) {
        setFirst(pin);
        setPin('');
        setStep('again');
        sayKey('pin_again');
      }
    } else if (pin.length >= PIN_MIN) {
      if (pin !== first) {
        setPin('');
        setFirst('');
        setStep('pin');
        setNote('pin_differs');
        sayKey('pin_differs');
      } else void save(pin);
    }
  };

  if (step === 'scopes') {
    return (
      <Page icon="person-help" title="mh_add" prompt="mh_what">
        <div class="flex flex-col gap-3" role="group" aria-label={t('mh_what')}>
          {SCOPES.map((scope) => {
            const on = scopes.has(scope);
            return (
              <button
                key={scope}
                type="button"
                role="switch"
                aria-checked={on}
                onClick={() => {
                  const next = new Set(scopes);
                  if (on) next.delete(scope);
                  else next.add(scope);
                  setScopes(next);
                }}
                class={
                  'flex min-h-tap-lg w-full items-center gap-3 rounded-lg border-2 px-3 py-2 text-start ' +
                  (on ? 'border-primary bg-primary-soft text-primary-strong' : 'border-line-strong bg-surface text-ink')
                }
              >
                <Pictogram name={SCOPE_ICON[scope] ?? 'document'} size={48} />
                <span class="flex-1 text-xl font-semibold">{t(SCOPE_KEY[scope]!)}</span>
                <Pictogram name={on ? 'yes' : 'no'} size={36} class={on ? 'text-primary' : 'text-ink-muted'} />
              </button>
            );
          })}
        </div>
        <Button size="lg" icon="forward" block disabled={scopes.size === 0} onClick={() => setStep('pin')} class="mt-auto">
          {t('next')}
        </Button>
        <Button size="md" variant="quiet" icon="back" block onClick={() => setStep('phone')}>
          {t('back')}
        </Button>
      </Page>
    );
  }

  const phone = step === 'phone';
  return (
    <Page icon="person-help" title="mh_add" prompt={phone ? 'mh_phone' : step === 'pin' ? 'mh_pin' : 'pin_again'}>
      {phone ? (
        <>
          <p id="helper-phone-label" class="text-lg font-semibold">
            {t('login_phone_label')}
          </p>
          <PhoneSlots digits={local} labelledBy="helper-phone-label" invalid={checkPhone(local) === 'not_mock'} />
        </>
      ) : (
        <>
          <PinDots count={pin.length} />
          {step === 'pin' ? <p class="text-base text-ink-muted">{t('mh_pin_hint')}</p> : null}
        </>
      )}
      {note ? <Notice tone="warn" icon="warning" text={t(note)} /> : null}
      {failure ? <InlineFailure failure={failure} /> : null}
      <Keypad
        onDigit={digit}
        onDelete={del}
        onDone={onDone}
        doneEnabled={phone ? local.length === PHONE_LENGTH : pin.length >= PIN_MIN}
        disabled={busy}
        busy={busy}
      />
    </Page>
  );
}

/** The pages of "My information" beyond consents: access log, fix, download, delete, requests, helpers. */
export default function MoreData({ parts }: { parts: readonly string[] }) {
  const [page, sub, ...rest] = parts;
  if (rest.length > 0) return <CitizenNotFoundPage />;
  // Deleting and choosing helpers are the person's own: a helper acting for a family never sees them.
  const ownOnly = acting.value !== null;
  switch (page) {
    case 'access':
      return sub ? <CitizenNotFoundPage /> : <AccessLogPage />;
    case 'fix':
      return sub ? <CitizenNotFoundPage /> : <FixPage />;
    case 'download':
      return sub ? <CitizenNotFoundPage /> : <DownloadPage />;
    case 'requests':
      return sub ? <CitizenNotFoundPage /> : <RequestsPage />;
    case 'delete':
      return ownOnly ? <Denied /> : sub ? <CitizenNotFoundPage /> : <DeletePage />;
    case 'helpers':
      return ownOnly ? <Denied /> : sub === undefined ? <HelpersPage /> : sub === 'new' ? <NewHelperPage /> : <CitizenNotFoundPage />;
    default:
      return <CitizenNotFoundPage />;
  }
}

function Denied() {
  const { route } = useLocation();
  return (
    <CitizenShell onBack={() => route('/my-data')}>
      <ScreenState kind="denied" />
    </CitizenShell>
  );
}
