import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type ApiFailure, type Result } from '../../shared/api/problem';
import type { AppealOut, ApplicationOut, ComplaintOut } from '../../shared/api/types';
import { unlockAudio } from '../../shared/audio';
import { AudioPrompt, type Speech } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { Spinner } from '../../shared/components/Spinner';
import { lang, t, type Key } from '../../shared/i18n';
import '../../shared/i18n/more';
import { go } from '../../shared/routing';
import { useSpeechInput } from '../../shared/speechInput';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { AnswerButton, AnswerGroup, NextButton, Notice, sayKey } from '../apply/parts';
import { enqueueReport, opPhase, opResults, ops, runOutbox } from '../apply/outbox';
import { CitizenShell } from '../CitizenShell';
import { PaperStar, SectionTitle } from '../JourneyPath';
import { formatDate, useApplication } from '../result/data';

// ---- small shared pieces -----------------------------------------------------------------------

type Load<T> = { state: 'loading' } | { state: 'failed'; failure: ApiFailure } | { state: 'ready'; data: T };

/** Run one API read on mount and again on retry. */
function useLoad<T>(read: () => Promise<Result<T>>): [Load<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Load<T>>({ state: 'loading' });
  useEffect(() => {
    let live = true;
    setLoaded({ state: 'loading' });
    void read().then((result) => {
      if (live) setLoaded(result.ok ? { state: 'ready', data: result.data } : { state: 'failed', failure: result.failure });
    });
    return () => {
      live = false;
    };
  }, [attempt]);
  return [loaded, () => setAttempt((n) => n + 1)];
}

const readAppeals = () => call(api.GET('/v1/me/appeals'));

interface Option {
  id: string;
  icon: PictogramName;
  label: Key;
}

function Dots({ at, total }: { at: number; total: number }) {
  return (
    <div role="progressbar" aria-valuemin={1} aria-valuemax={total} aria-valuenow={at + 1} aria-label={t('apply_progress', { current: at + 1, total })} class="flex items-center justify-center gap-2 py-1">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} class={`size-3 rounded-full border-2 ${i <= at ? 'border-primary bg-primary' : 'border-ink-muted'}`} />
      ))}
    </div>
  );
}

function Heading({ icon, title, tone = 'text-primary' }: { icon: PictogramName; title: Key; tone?: string }) {
  const ref = useFocusOnMount<HTMLHeadingElement>();
  return (
    <div class="flex items-center gap-4">
      <Pictogram name={icon} size={56} class={tone} />
      <h1 ref={ref} tabIndex={-1} class="text-2xl font-bold">
        {t(title)}
      </h1>
    </div>
  );
}

const speechOf = (keys: readonly Key[], id: string): Speech => ({
  id: `${id}:${lang.value}`,
  items: keys.map((key) => ({ key, text: t(key) })),
  lang: lang.value,
});

// ---- the optional note: spoken (read back and confirmed) or typed -----------------------------

const NOTE_MAX = 500;

function NoteStep({ note, onNote }: { note: string; onNote: (text: string) => void }) {
  const speech = useSpeechInput(lang.value);
  const [typing, setTyping] = useState(false);
  const heard = speech.input.state === 'heard' ? speech.input.text.slice(0, NOTE_MAX) : null;
  const failed = speech.input.state === 'failed' ? speech.input.why : null;
  const blocked = failed === 'denied' || failed === 'unavailable';
  useEffect(() => {
    if (failed) sayKey(blocked ? 'rp_mic_off' : 'voice_nothing');
  }, [failed]);

  const listen = (): void => {
    unlockAudio();
    speech.start();
  };

  if (speech.input.state === 'listening') {
    return (
      <div class="flex flex-col gap-3">
        <p role="status" class="flex min-h-tap-lg items-center justify-center gap-3 rounded-lg border-2 border-primary bg-primary-soft px-3 text-xl font-semibold text-primary-strong">
          <Pictogram name="microphone" size={40} />
          {speech.input.partial ? <span dir="auto">{speech.input.partial}</span> : t('voice_listening')}
        </p>
        <Button size="md" variant="neutral" icon="pause" block onClick={speech.stop}>
          {t('voice_stop')}
        </Button>
      </div>
    );
  }
  // What the phone heard is read back, and kept only after the yes icon.
  if (heard) {
    return (
      <section aria-label={t('voice_heard')} class="flex flex-col gap-3 rounded-lg border-2 border-primary bg-paper p-3">
        <div class="flex items-start justify-between gap-2">
          <p class="text-xl font-semibold" dir="auto">
            {heard}
          </p>
          <AudioPrompt speech={{ id: `note:${heard}`, items: [{ key: 'rp_note_heard', text: heard }], lang: lang.value }} autoPlay class="shrink-0" />
        </div>
        <Button
          size="lg"
          icon="yes"
          block
          onClick={() => {
            onNote(heard);
            speech.reset();
          }}
        >
          {t('voice_ok_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block onClick={listen}>
          {t('voice_ok_no')}
        </Button>
      </section>
    );
  }
  if (note && !typing) {
    return (
      <div class="flex flex-col gap-3">
        <p class="rounded-lg border-2 border-line-strong bg-surface p-3 text-lg" dir="auto">
          {note}
        </p>
        <Button size="md" variant="neutral" icon="delete" block onClick={() => onNote('')}>
          {t('rp_note_remove')}
        </Button>
      </div>
    );
  }
  return (
    <div class="flex flex-col gap-3">
      {failed ? <Notice tone="warn" icon="microphone" text={t(blocked ? 'rp_mic_off' : 'voice_nothing')} /> : null}
      {typing ? (
        <label class="flex flex-col gap-2 text-lg font-semibold">
          {t('rp_note_label')}
          <textarea
            dir="auto"
            rows={4}
            maxLength={NOTE_MAX}
            value={note}
            onInput={(event) => onNote(event.currentTarget.value)}
            class="min-h-32 w-full rounded-lg border-2 border-line-strong bg-paper p-3 text-lg font-normal"
          />
        </label>
      ) : (
        <>
          {blocked ? null : (
            <Button size="lg" variant="secondary" icon="microphone" block onClick={listen}>
              {t(failed ? 'voice_again' : 'rp_say')}
            </Button>
          )}
          <Button size="lg" variant="secondary" icon="edit" block onClick={() => setTyping(true)}>
            {t('rp_write')}
          </Button>
        </>
      )}
    </div>
  );
}

// ---- the three steps and what follows ----------------------------------------------------------

interface FlowSpec {
  icon: PictogramName;
  ask: Key;
  confirm: Key;
  doneTitle: Key;
  doneBody: Key;
  options: readonly Option[];
  back: string;
  /** Put the request in the outbox (it goes out at once when there is a connection). */
  queue: (choice: Option, note: string, key: string) => string;
  /** The label of the status the server returned. */
  status: (data: never) => Key;
  after?: ComponentChildren;
}

const WHY: Readonly<Record<string, Key>> = {
  appeal_window_closed: 'ap_e_window',
  appeal_already_open: 'ap_e_open',
  appeal_already_decided: 'ap_e_decided',
  appeal_not_applicable: 'ap_e_na',
  consent_required: 'rp_e_consent',
};

/** A refusal the person can understand and cannot fix by trying again: a keyed message, never the server's text. */
function Refused({ failure, code }: { failure: ApiFailure; code: string }) {
  const days = (failure.problem as { window_days?: number } | undefined)?.window_days ?? 30;
  const key = WHY[code] as Key;
  const text = t(key, { days });
  useEffect(() => sayKey(key), [key]);
  return (
    <>
      <Notice tone="warn" icon="warning" text={text}>
        <AudioPrompt speech={{ id: `refused:${key}:${lang.value}`, items: [{ key, text }], lang: lang.value }} />
      </Notice>
      {code === 'consent_required' ? <GoTo path="/my-data" icon="lock" label="home_my_data" /> : null}
    </>
  );
}

function GoTo({ path, icon, label }: { path: string; icon: PictogramName; label: Key }) {
  const { route } = useLocation();
  return (
    <Button size="lg" variant="secondary" icon={icon} block onClick={() => go(route, path)}>
      {t(label)}
    </Button>
  );
}

/** After Send: sending, saved on the phone (no network), sent, or refused. */
function Sent({ id, spec, again }: { id: string; spec: FlowSpec; again: () => void }) {
  const { route } = useLocation();
  const result = opResults.value.get(id);
  const queued = ops.value.find((op) => op.id === id);
  const home = (
    <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')} class="mt-auto">
      {t('go_home')}
    </Button>
  );
  if (result?.state === 'done') {
    const data = result.result as AppealOut | ComplaintOut;
    const message = data.message?.[lang.value];
    return (
      <CitizenShell onBack={() => route('/')} speech={speechOf([spec.doneTitle, spec.doneBody], 'sent')}>
        <Heading icon="yes" title={spec.doneTitle} />
        <p class="text-lg text-ink">{t(spec.doneBody)}</p>
        <div role="status" class="flex flex-col gap-2 rounded-lg border-2 border-line-strong bg-surface p-3">
          <p class="flex items-center gap-2 text-lg font-bold">
            <Pictogram name="clock" size={32} class="text-primary" />
            {t('rp_status')}: {t(spec.status(data as never))}
          </p>
          {message ? <p class="text-base text-ink">{message}</p> : null}
        </div>
        {spec.after}
        {home}
      </CitizenShell>
    );
  }
  if (result?.state === 'failed') {
    const code = result.failure.problem?.code ?? '';
    return (
      <CitizenShell onBack={again}>
        {WHY[code] ? <Refused failure={result.failure} code={code} /> : <FailureState failure={result.failure} onRetry={again} />}
        {home}
      </CitizenShell>
    );
  }
  const phase = queued ? opPhase(queued) : 'sending';
  return (
    <CitizenShell onBack={() => route('/')} prompt={phase === 'sending' ? undefined : 'outbox_stored'}>
      {phase === 'sending' ? (
        <ScreenState kind="loading" body={t('outbox_sending')} />
      ) : (
        <Notice tone="warn" icon="phone-saved" text={t('outbox_stored')}>
          <AudioPrompt prompt="outbox_stored" autoPlay />
        </Notice>
      )}
      {phase === 'sending' ? null : home}
    </CitizenShell>
  );
}

function ReportFlow({ spec }: { spec: FlowSpec }) {
  const { route } = useLocation();
  const [step, setStep] = useState(0);
  const [choice, setChoice] = useState<Option | null>(null);
  const [note, setNote] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  if (sent) {
    return (
      <Sent
        id={sent}
        spec={spec}
        again={() => {
          setSent(null);
          setStep(2);
        }}
      />
    );
  }
  const back = step === 0 ? () => route(spec.back) : () => setStep(step - 1);
  const progress = <Dots at={step} total={3} />;
  if (step === 0) {
    return (
      <CitizenShell onBack={back} prompt={spec.ask} progress={progress}>
        <Heading icon={spec.icon} title={spec.ask} />
        <AnswerGroup>
          {spec.options.map((option) => (
            <AnswerButton
              key={option.id}
              icon={option.icon}
              label={t(option.label)}
              selected={choice?.id === option.id}
              onSelect={() => {
                setChoice(option);
                sayKey(option.label);
              }}
            />
          ))}
        </AnswerGroup>
        <NextButton enabled={choice !== null} onNext={() => setStep(1)} />
      </CitizenShell>
    );
  }
  if (step === 1) {
    return (
      <CitizenShell onBack={back} prompt="rp_note_title" progress={progress}>
        <Heading icon="message" title="rp_note_title" />
        <p class="text-lg text-ink-muted">{t('rp_note_prompt')}</p>
        <NoteStep note={note} onNote={setNote} />
        <Button size="lg" icon="forward" block onClick={() => setStep(2)} class="mt-auto">
          {t(note ? 'next' : 'rp_skip')}
        </Button>
      </CitizenShell>
    );
  }
  const send = (): void => {
    if (!choice) return;
    // One key for this request: every try is the same request, so it can never be filed twice.
    setSent(spec.queue(choice, note.trim(), crypto.randomUUID()));
    void runOutbox();
  };
  return (
    <CitizenShell onBack={back} speech={speechOf([spec.confirm, choice?.label ?? 'rp_change'], `confirm:${choice?.id}`)} progress={progress}>
      <Heading icon="yes" title={spec.confirm} />
      {choice ? (
        <div class="flex items-center gap-3 rounded-lg border-2 border-line-strong bg-surface p-3">
          <Pictogram name={choice.icon} size={56} class="text-primary" />
          <p class="text-xl font-semibold">{t(choice.label)}</p>
        </div>
      ) : null}
      {note ? (
        <p class="rounded-lg border-2 border-line bg-paper p-3 text-lg" dir="auto">
          {note}
        </p>
      ) : null}
      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" icon="yes" block onClick={send}>
          {t('rp_send_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block onClick={() => setStep(0)}>
          {t('rp_change')}
        </Button>
      </div>
    </CitizenShell>
  );
}

// ---- appeals -----------------------------------------------------------------------------------

const REASONS: readonly Option[] = [
  { id: 'income', icon: 'income-1', label: 'ap_why_income' },
  { id: 'papers', icon: 'document', label: 'ap_why_papers' },
  { id: 'details', icon: 'edit', label: 'ap_why_details' },
  { id: 'other', icon: 'unknown', label: 'ap_why_other' },
];

const APPEAL_LABEL: Record<AppealOut['status_key'], Key> = {
  being_checked: 'ap_s_being_checked',
  first_answer_stays: 'ap_s_first_answer_stays',
  approved_after_appeal: 'ap_s_approved_after_appeal',
  withdrawn: 'ap_s_withdrawn',
};
const APPEAL_ICON: Record<AppealOut['status_key'], PictogramName> = {
  being_checked: 'person-help',
  first_answer_stays: 'document',
  approved_after_appeal: 'yes',
  withdrawn: 'no',
};

const APPEAL_SPEC = (app: ApplicationOut): FlowSpec => ({
  icon: 'person-help',
  ask: 'ap_why_title',
  confirm: 'ap_confirm_prompt',
  doneTitle: 'ap_done_title',
  doneBody: 'ap_done_body',
  options: REASONS,
  back: '/track',
  // The reason staff read is always English, whatever language the person uses; their own note follows it.
  queue: (choice, note, key) =>
    enqueueReport({ kind: 'appeal', key, text: note ? `${t(choice.label as Key, undefined, 'en')}: ${note}` : t(choice.label as Key, undefined, 'en') }, app.id).id,
  status: (data: AppealOut) => APPEAL_LABEL[data.status_key],
});

/** One appeal as a star: its status, the date, and the server's keyed message (as text). */
function AppealStar({ appeal }: { appeal: AppealOut }) {
  const key = appeal.status_key;
  // The server text for an approval names an amount the list does not carry, so that status uses our own sentence only.
  const message = key === 'approved_after_appeal' ? null : appeal.message[lang.value];
  return (
    <div class="flex gap-4" aria-current="step">
      <PaperStar now>
        <Pictogram name={APPEAL_ICON[key]} size={26} />
      </PaperStar>
      <div class="flex flex-col gap-1 pb-2 pt-2">
        <p class="text-lg font-semibold">{t(APPEAL_LABEL[key])}</p>
        <time dateTime={appeal.created_at} class="text-sm text-ink-muted">
          {formatDate(appeal.created_at, lang.value)}
        </time>
        {message ? <p class="text-base text-ink">{message}</p> : null}
      </div>
    </div>
  );
}

function AppealScreen() {
  const { route } = useLocation();
  const { loaded, reload } = useApplication(true);
  const [appeals, reloadAppeals] = useLoad(readAppeals);
  const shell = (children: ComponentChildren) => (
    <CitizenShell onBack={() => route(loaded.state === 'ready' ? '/track' : '/')}>{children}</CitizenShell>
  );
  if (loaded.state === 'failed') return shell(<FailureState failure={loaded.failure} onRetry={reload} />);
  if (appeals.state === 'failed') return shell(<FailureState failure={appeals.failure} onRetry={reloadAppeals} />);
  if (loaded.state === 'loading' || appeals.state === 'loading') return shell(<ScreenState kind="loading" />);
  if (loaded.state === 'empty') {
    return shell(
      <ScreenState kind="empty" title={t('track_empty_title')} body={t('track_empty_body')}>
        <GoTo path="/apply" icon="document" label="home_apply" />
      </ScreenState>,
    );
  }
  const app = loaded.app;
  const mine = appeals.data.items.filter((item) => item.application_id === app.id);
  const latest = mine[0];
  // Already asked, or nothing to ask about: show where it stands instead of the form.
  if ((latest && latest.status !== 'withdrawn') || app.status !== 'rejected') {
    return shell(
      <>
        <Heading icon="person-help" title="ap_track_title" />
        {latest ? <AppealStar appeal={latest} /> : <Notice tone="check" icon="document" text={t('ap_e_na')} />}
        <GoTo path="/track" icon="clock" label="home_see_application" />
      </>,
    );
  }
  return <ReportFlow spec={APPEAL_SPEC(app)} />;
}

/** In the tracker: the appeal's status as the last star, or the way to ask again when the application was rejected. */
export function TrackAppeal({ app }: { app: ApplicationOut }) {
  const { route } = useLocation();
  const [appeals, reload] = useLoad(readAppeals);
  if (appeals.state === 'loading') {
    return (
      <p role="status" class="flex items-center gap-2 text-base text-ink-muted">
        <Spinner size={24} />
        {t('state_loading')}
      </p>
    );
  }
  if (appeals.state === 'failed') {
    return (
      <Notice tone="warn" icon="offline" text={t(appeals.failure.kind === 'offline' ? 'state_offline_body' : 'state_error_body')}>
        <Button size="md" variant="neutral" icon="retry" onClick={reload}>
          {t('retry')}
        </Button>
      </Notice>
    );
  }
  const latest = appeals.data.items.find((item) => item.application_id === app.id);
  if (latest) {
    return (
      <section aria-labelledby="track-appeal" class="flex flex-col gap-3">
        <SectionTitle id="track-appeal">{t('ap_track_title')}</SectionTitle>
        <AppealStar appeal={latest} />
      </section>
    );
  }
  return app.status === 'rejected' ? (
    <Button size="lg" icon="person-help" block onClick={() => go(route, '/appeal')}>
      {t('appeal_ask')}
    </Button>
  ) : null;
}

// ---- complaints --------------------------------------------------------------------------------

const CATEGORIES: readonly Option[] = [
  { id: 'service', icon: 'warning', label: 'cp_cat_service' },
  { id: 'staff', icon: 'person', label: 'cp_cat_staff' },
  { id: 'scam_attempt', icon: 'msg-scam', label: 'cp_cat_scam' },
  { id: 'other', icon: 'message', label: 'cp_cat_other' },
];

const CATEGORY_LABEL: Record<ComplaintOut['category'], Key> = {
  service: 'cp_cat_service',
  staff: 'cp_cat_staff',
  scam_attempt: 'cp_cat_scam',
  payment: 'cp_cat_payment',
  other: 'cp_cat_other',
};
const CATEGORY_ICON: Record<ComplaintOut['category'], PictogramName> = {
  service: 'warning',
  staff: 'person',
  scam_attempt: 'msg-scam',
  payment: 'payment',
  other: 'message',
};
const COMPLAINT_LABEL: Record<ComplaintOut['status'], Key> = {
  received: 'cp_s_received',
  being_checked: 'cp_s_being_checked',
  resolved: 'cp_s_resolved',
};

/** For a scam attempt: a gentle way to check the message itself. */
function ScamLink() {
  return <GoTo path="/scam" icon="shield" label="cp_scam_link" />;
}

const COMPLAINT_SPEC: FlowSpec = {
  icon: 'warning',
  ask: 'cp_what_title',
  confirm: 'cp_confirm_prompt',
  doneTitle: 'cp_done_title',
  doneBody: 'cp_done_body',
  options: CATEGORIES,
  back: '/',
  queue: (choice, note, key) =>
    enqueueReport({ kind: 'complaint', key, category: choice.id as ComplaintOut['category'], text: note }, null).id,
  status: (data: ComplaintOut) => COMPLAINT_LABEL[data.status],
  after: <ScamLink />,
};

function MyComplaints() {
  const { route } = useLocation();
  const [list, reload] = useLoad(() => call(api.GET('/v1/me/complaints')));
  const back = () => route('/my-data');
  if (list.state !== 'ready') {
    return <CitizenShell onBack={back}>{list.state === 'failed' ? <FailureState failure={list.failure} onRetry={reload} /> : <ScreenState kind="loading" />}</CitizenShell>;
  }
  const items = list.data.items;
  return (
    <CitizenShell onBack={back} prompt="cp_list_title">
      <Heading icon="message" title="cp_list_title" />
      {items.length === 0 ? (
        <ScreenState kind="empty" heading="h2" title={t('cp_list_empty_title')} body={t('cp_list_empty_body')} />
      ) : (
        <ul class="flex flex-col gap-3">
          {items.map((item) => (
            <li key={item.id} class="flex items-start gap-3 rounded-lg border-2 border-line-strong bg-paper p-3">
              <Pictogram name={CATEGORY_ICON[item.category]} size={48} class="text-primary" />
              <div class="flex flex-1 flex-col gap-1">
                <p class="text-lg font-semibold">{t(CATEGORY_LABEL[item.category])}</p>
                <p class="text-base font-semibold text-primary-strong">{t(COMPLAINT_LABEL[item.status])}</p>
                <time dateTime={item.created_at} class="text-sm text-ink-muted">
                  {formatDate(item.created_at, lang.value)}
                </time>
                <p class="text-base text-ink">{item.message[lang.value]}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <GoTo path="/report" icon="message" label="home_report" />
    </CitizenShell>
  );
}

// ---- the routes --------------------------------------------------------------------------------

/** /appeal, /report and /my-data/complaints. A lazy chunk: the first screens never wait for it. */
export default function ReportPages({ view }: { view: 'appeal' | 'report' | 'complaints' }) {
  if (view === 'appeal') return <AppealScreen />;
  if (view === 'complaints') return <MyComplaints />;
  return <ReportFlow spec={COMPLAINT_SPEC} />;
}
