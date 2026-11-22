import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type ApiFailure, type Result } from '../../shared/api/problem';
import type { AppealOut, ApplicationOut, ComplaintOut } from '../../shared/api/types';
import { unlockAudio } from '../../shared/audio';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { lang, t, type Key } from '../../shared/i18n';
import '../../shared/i18n/more';
import { go } from '../../shared/routing';
import { useSpeechInput } from '../../shared/speechInput';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { AnswerButton, AnswerGroup, NextButton, Notice, sayKey } from '../apply/parts';
import { enqueueReport, opPhase, opResults, ops, runOutbox, type AppealOp, type ComplaintOp, type Outcome } from '../apply/outbox';
import { CitizenShell } from '../CitizenShell';
import { PaperStar, SectionTitle } from '../JourneyPath';
import { appealNow, formatDate, useApplication } from '../result/data';
import { WithApplication } from '../result/TrackerScreen';

// ---- the outbox sender -------------------------------------------------------------------------

/** A refusal that will not change on a retry (a closed window, no consent) leaves the queue; a weak network does not. */
function outcomeFor(failure: ApiFailure): Outcome {
  switch (failure.kind) {
    case 'offline':
      return { type: 'wait', why: 'offline' };
    case 'unauthenticated':
      return { type: 'wait', why: 'session' };
    case 'network':
    case 'server':
    case 'rate_limited':
      return { type: 'retry', failure };
    default:
      return { type: 'drop', failure };
  }
}

/** The outbox transport for the two new op kinds. The same Idempotency-Key goes with every try, so a lost answer never files twice. */
export async function sendReport(op: AppealOp | ComplaintOp): Promise<Outcome> {
  const headers = { 'Idempotency-Key': op.key };
  const result =
    op.kind === 'appeal'
      ? op.app
        ? await call(api.POST('/v1/appeals', { body: { application_id: op.app, reason: op.text }, headers }))
        : null
      : await call(api.POST('/v1/complaints', { body: { category: op.category, ...(op.text ? { details: op.text } : {}) }, headers }));
  if (!result) return { type: 'wait', why: 'create' };
  return result.ok ? { type: 'done', result: result.data } : outcomeFor(result.failure);
}

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

function Heading({ icon, title }: { icon: PictogramName; title: Key }) {
  const ref = useFocusOnMount<HTMLHeadingElement>();
  return (
    <div class="flex items-center gap-4">
      <Pictogram name={icon} size={56} class="text-primary" />
      <h1 ref={ref} tabIndex={-1} class="text-2xl font-bold">
        {t(title)}
      </h1>
    </div>
  );
}

// ---- the optional note: spoken (read back and confirmed) or typed -----------------------------

const NOTE_MAX = 500;

function NoteStep({ note, onNote, onNext }: { note: string; onNote: (text: string) => void; onNext: () => void }) {
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
            setTyping(true);
            speech.reset();
          }}
        >
          {t('voice_ok_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block onClick={listen}>
          {t('scam_heard_no')}
        </Button>
      </section>
    );
  }
  const next = (
    <Button size="lg" icon="forward" block onClick={onNext} class="mt-4">
      {t('next')}
    </Button>
  );
  return (
    <div class="flex flex-col gap-3">
      {failed ? <Notice tone="warn" icon="microphone" text={t(blocked ? 'rp_mic_off' : 'voice_nothing')} /> : null}
      {typing || note ? (
        <label class="flex flex-col gap-2 text-lg font-semibold">
          {t('rp_write')}
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
              {t(failed ? 'voice_again' : 'voice_say')}
            </Button>
          )}
          <Button size="lg" variant="secondary" icon="edit" block onClick={() => setTyping(true)}>
            {t('rp_write')}
          </Button>
        </>
      )}
      {next}
    </div>
  );
}

// ---- the three steps and what follows ----------------------------------------------------------

interface Spec {
  icon: PictogramName;
  ask: Key;
  /** What the person is told after sending. */
  done: Key;
  options: readonly Option[];
  back: string;
  /** Put the request in the outbox; it goes out at once when there is a connection. */
  queue: (choice: Option, note: string, key: string) => string;
  /** The server's status word: the key of its label. */
  status: (data: never) => Key;
  after?: (choice: Option | null) => ComponentChildren;
}

const WHY: Readonly<Record<string, Key>> = {
  appeal_window_closed: 'ap_e_window',
  appeal_already_open: 'ap_s_being_checked',
  appeal_already_decided: 'ap_s_first_answer_stays',
  appeal_not_applicable: 'ap_e_na',
  consent_required: 'apply_need_consent',
};

function GoTo({ path, icon, label }: { path: string; icon: PictogramName; label: Key }) {
  const { route } = useLocation();
  return (
    <Button size="lg" variant="secondary" icon={icon} block onClick={() => go(route, path)}>
      {t(label)}
    </Button>
  );
}

/** After Send: sending, saved on the phone, sent, or refused with a keyed message (never the server's text). */
function Sent({ id, spec, choice, again }: { id: string; spec: Spec; choice: Option | null; again: () => void }) {
  const { route } = useLocation();
  const result = opResults.value.get(id);
  const queued = ops.value.find((op) => op.id === id);
  const phase = queued ? opPhase(queued) : 'sending';
  const failure = result?.state === 'failed' ? result.failure : null;
  const why = failure?.problem?.code ? WHY[failure.problem.code] : undefined;
  const waiting = !result && phase !== 'sending';
  const key: Key = why ?? (queued && queued.tries > 0 ? 'rp_retrying' : 'outbox_stored');
  const text = t(key, { days: (failure?.problem as { window_days?: number } | undefined)?.window_days ?? 30 });
  const data = result?.state === 'done' ? (result.result as AppealOut | ComplaintOut) : null;
  return (
    <CitizenShell
      onBack={failure ? again : () => route('/')}
      prompt={data ? spec.done : undefined}
      speech={why || waiting ? { id: `${key}:${lang.value}`, items: [{ key, text }], lang: lang.value } : undefined}
    >
      {data ? (
        <>
          <Heading icon="yes" title="outbox_sent" />
          <p class="text-lg text-ink">{t(spec.done)}</p>
          <div role="status" class="flex flex-col gap-2 rounded-lg border-2 border-line-strong bg-surface p-3">
            <p class="text-lg font-bold">{t(spec.status(data as never))}</p>
            <p class="text-base text-ink">{data.message[lang.value].replace(/-/g, '‑')}</p>
          </div>
          {spec.after?.(choice)}
        </>
      ) : failure && !why ? (
        <FailureState failure={failure} onRetry={again} />
      ) : why || waiting ? (
        <>
          <Notice tone="warn" icon={why ? 'warning' : 'phone-saved'} text={text} />
          {why === WHY['consent_required'] ? <GoTo path="/my-data" icon="lock" label="home_my_data" /> : null}
        </>
      ) : (
        <ScreenState kind="loading" body={t('outbox_sending')} />
      )}
      {phase === 'sending' && !result ? null : (
        <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')} class="mt-auto">
          {t('go_home')}
        </Button>
      )}
    </CitizenShell>
  );
}

function ReportFlow({ spec }: { spec: Spec }) {
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
        choice={choice}
        again={() => {
          setSent(null);
          setStep(2);
        }}
      />
    );
  }
  const back = step === 0 ? () => route(spec.back) : () => setStep(step - 1);
  const prompt: Key = step === 0 ? spec.ask : step === 1 ? 'rp_note_title' : 'rp_confirm';
  return (
    <CitizenShell onBack={back} prompt={prompt} progress={<Dots at={step} total={3} />}>
      <Heading icon={step === 1 ? 'message' : spec.icon} title={prompt} />
      {step === 0 ? (
        <>
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
        </>
      ) : step === 1 ? (
        <NoteStep note={note} onNote={setNote} onNext={() => setStep(2)} />
      ) : (
        <>
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
            <Button
              size="lg"
              icon="yes"
              block
              onClick={() => {
                // One key for this request: every try is the same request, so it can never be filed twice.
                if (choice) setSent(spec.queue(choice, note.trim(), crypto.randomUUID()));
                void runOutbox();
              }}
            >
              {t('answer_yes')}
            </Button>
            <Button size="lg" variant="neutral" icon="no" block onClick={() => setStep(0)}>
              {t('answer_no')}
            </Button>
          </div>
        </>
      )}
    </CitizenShell>
  );
}

// ---- appeals -----------------------------------------------------------------------------------

const REASONS: readonly Option[] = [
  { id: 'income', icon: 'payment', label: 'ap_why_income' },
  { id: 'papers', icon: 'document', label: 'ap_why_papers' },
  { id: 'details', icon: 'edit', label: 'ap_why_details' },
  { id: 'other', icon: 'unknown', label: 'cp_cat_other' },
];

type StatusKey = AppealOut['status_key'];
const APPEAL_ICON: Record<StatusKey, PictogramName> = {
  being_checked: 'person-help',
  first_answer_stays: 'document',
  approved_after_appeal: 'yes',
  withdrawn: 'no',
};
const appealLabel = (key: StatusKey): Key => (key === 'withdrawn' ? 'status_withdrawn' : (`ap_s_${key}` as Key));

const appealSpec = (app: ApplicationOut): Spec => ({
  icon: 'person-help',
  ask: 'ap_why_title',
  done: 'ap_done_body',
  options: REASONS,
  back: '/track',
  // The reason staff read is always English, whatever language the person uses; their own note follows it.
  queue: (choice, note, key) => {
    const why = t(choice.label, undefined, 'en');
    return enqueueReport({ kind: 'appeal', key, text: note ? `${why}: ${note}` : why }, app.id).id;
  },
  status: (data: AppealOut) => appealLabel(data.status_key),
  after: () => <GoTo path="/track" icon="clock" label="home_see_application" />,
});

/** One appeal as a star: its status, the date, and the server's keyed message (as text). */
function AppealStar({ appeal }: { appeal: AppealOut }) {
  const key = appeal.status_key;
  // The server text for an approval names an amount the list does not carry, so that status uses our own sentence only.
  const message = key === 'approved_after_appeal' ? null : appeal.message[lang.value];
  return (
    <div class="flex gap-4" aria-current="step">
      <PaperStar now={key === 'being_checked' || key === 'approved_after_appeal'}>
        <Pictogram name={APPEAL_ICON[key]} size={26} />
      </PaperStar>
      <div class="flex flex-col gap-1 pb-2 pt-2">
        <p class="text-lg font-semibold">{t(appealLabel(key))}</p>
        <time dateTime={appeal.created_at} class="text-sm text-ink-muted">
          {formatDate(appeal.created_at, lang.value)}
        </time>
        {message ? <p class="text-base text-ink">{message}</p> : null}
      </div>
    </div>
  );
}

function AppealScreen() {
  const { loaded, reload } = useApplication(true);
  return (
    <WithApplication loaded={loaded} reload={reload}>
      {(app) => <AppealFor app={app} />}
    </WithApplication>
  );
}

function AppealFor({ app }: { app: ApplicationOut }) {
  const { route } = useLocation();
  const [appeals, reload] = useLoad(readAppeals);
  if (appeals.state !== 'ready') {
    return (
      <CitizenShell onBack={() => route('/track')}>
        {appeals.state === 'failed' ? <FailureState failure={appeals.failure} onRetry={reload} /> : <ScreenState kind="loading" />}
      </CitizenShell>
    );
  }
  const latest = appeals.data.items.find((item) => item.application_id === app.id);
  // Already asked, or nothing to ask about: show where it stands instead of the form.
  if ((latest && latest.status !== 'withdrawn') || app.status !== 'rejected') {
    return (
      <CitizenShell onBack={() => route('/track')}>
        <Heading icon="person-help" title="appeal_ask" />
        {latest ? <AppealStar appeal={latest} /> : <Notice tone="check" icon="document" text={t('ap_e_na')} />}
        <GoTo path="/track" icon="clock" label="home_see_application" />
      </CitizenShell>
    );
  }
  return <ReportFlow spec={appealSpec(app)} />;
}

/** In the tracker: the appeal's status as a star, or the way to ask when the application was rejected. */
export function TrackAppeal({ app }: { app: ApplicationOut }) {
  const { route } = useLocation();
  const [appeals, reload] = useLoad(readAppeals);
  useEffect(() => () => void (appealNow.value = false), []);
  if (appeals.state === 'loading') return null;
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
  appealNow.value = latest?.status_key === 'being_checked' || latest?.status_key === 'approved_after_appeal';
  if (latest) {
    return (
      <section aria-labelledby="track-appeal" class="flex flex-col gap-3">
        <SectionTitle id="track-appeal">{t('appeal_ask')}</SectionTitle>
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

type Category = ComplaintOut['category'];
const CAT: Record<Category, Option> = {
  service: { id: 'service', icon: 'warning', label: 'cp_cat_service' },
  staff: { id: 'staff', icon: 'person', label: 'cp_cat_staff' },
  scam_attempt: { id: 'scam_attempt', icon: 'msg-scam', label: 'cp_cat_scam' },
  payment: { id: 'payment', icon: 'payment', label: 'cp_cat_other' },
  other: { id: 'other', icon: 'message', label: 'cp_cat_other' },
};
const complaintLabel = (status: ComplaintOut['status']): Key => `cp_s_${status}` as Key;

const complaintSpec: Spec = {
  icon: 'warning',
  ask: 'cp_what_title',
  done: 'cp_done_body',
  options: [CAT.service, CAT.staff, CAT.scam_attempt, CAT.other],
  back: '/',
  queue: (choice, note, key) => enqueueReport({ kind: 'complaint', key, category: choice.id as Category, text: note }, null).id,
  status: (data: ComplaintOut) => complaintLabel(data.status),
  after: (choice) => (
    <>
      {choice?.id === 'scam_attempt' ? <GoTo path="/scam" icon="shield" label="home_scam" /> : null}
      <GoTo path="/my-data/complaints" icon="message" label="cp_list_title" />
    </>
  ),
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
        <ScreenState kind="empty" heading="h2" />
      ) : (
        <ul class="flex flex-col gap-3">
          {items.map((item) => (
            <li key={item.id} class="flex items-start gap-3 rounded-lg border-2 border-line-strong bg-paper p-3">
              <Pictogram name={CAT[item.category].icon} size={48} class="text-primary" />
              <div class="flex flex-1 flex-col gap-1">
                <p class="text-lg font-semibold">{t(CAT[item.category].label)}</p>
                <p class="text-base font-semibold text-primary-strong">{t(complaintLabel(item.status))}</p>
                <time dateTime={item.created_at} class="text-sm text-ink-muted">
                  {formatDate(item.created_at, lang.value)}
                </time>
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
  return <ReportFlow spec={complaintSpec} />;
}
