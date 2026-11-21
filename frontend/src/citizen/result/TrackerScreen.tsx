import type { ComponentChildren, ComponentType } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { ApplicationOut, DocumentView } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { lang, messageKeyFor, t } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure, Notice } from '../apply/parts';
import { PaperStar, SectionTitle } from '../JourneyPath';
import { PhotoButtons, PhotoPreview } from '../apply/PhotoParts';
import { usePhotoUpload } from '../apply/usePhotoUpload';
import { CitizenShell } from '../CitizenShell';
import { appealNow, formatDate, statusIcon, statusKey, useApplication, type Loaded } from './data';
import { ExplanationText, proofKindFor } from './ResultScreen';
import { TrackingCode } from './TrackingCode';

/** Loading, error and empty states shared by the screens that show one application. */
export function WithApplication({ loaded, reload, children }: { loaded: Loaded; reload: () => void; children: (app: ApplicationOut) => ComponentChildren }) {
  const { route } = useLocation();
  if (loaded.state === 'ready') return <>{children(loaded.app)}</>;
  return (
    <CitizenShell onBack={() => route('/')}>
      {loaded.state === 'loading' ? <ScreenState kind="loading" /> : null}
      {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={reload} /> : null}
      {loaded.state === 'empty' ? (
        <ScreenState kind="empty" title={t('track_empty_title')} body={t('track_empty_body')}>
          <Button size="lg" icon="document" block onClick={() => route('/apply')}>
            {t('home_apply')}
          </Button>
        </ScreenState>
      ) : null}
    </CitizenShell>
  );
}

/** An appeal's status as a star, or the way to ask again. Its chunk loads after the tracker, never before it. */
function AppealSection({ app }: { app: ApplicationOut }) {
  const [Part, setPart] = useState<ComponentType<{ app: ApplicationOut }> | null>(null);
  useEffect(() => {
    void import('../report/ReportPages').then((m) => setPart(() => m.TrackAppeal)).catch(() => undefined);
  }, []);
  return Part ? <Part app={app} /> : null;
}

/** Tracker (PLAN D1.4): the tracking code, the status timeline and the latest explanation. */
export function TrackerScreen() {
  const { loaded, reload } = useApplication(true);
  return (
    <WithApplication loaded={loaded} reload={reload}>
      {(app) => <Tracker app={app} />}
    </WithApplication>
  );
}

function Tracker({ app }: { app: ApplicationOut }) {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const code = lang.value;
  const timeline = [...(app.timeline ?? [])];
  return (
    <CitizenShell onBack={() => route('/')} prompt="track_prompt">
      <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
        {t('track_title')}
      </h1>
      <TrackingCode code={app.tracking_code} symbols={app.tracking_symbols ?? []} />

      <div class="flex items-center gap-3 rounded-2xl border-2 border-line-strong bg-surface/60 p-4">
        <span class="grid size-14 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
          <Pictogram name={statusIcon(app.status)} size={36} />
        </span>
        <p class="text-xl font-semibold">{t(statusKey(app.status))}</p>
      </div>

      {app.status === 'draft' ? (
        <Button size="lg" icon="forward" block onClick={() => route('/apply')}>
          {t('home_continue')}
        </Button>
      ) : null}

      {app.decision ? (
        <section aria-labelledby="track-latest" class="flex flex-col gap-2">
          <SectionTitle id="track-latest">{t('track_latest')}</SectionTitle>
          <ExplanationText explanation={app.decision.explanation} />
        </section>
      ) : null}

      {timeline.length > 0 ? (
        <section aria-labelledby="track-timeline" class="flex flex-col gap-3">
          <SectionTitle id="track-timeline">{t('track_timeline')}</SectionTitle>
          <ol class="flex flex-col">
            {timeline.map((item, index) => {
              const label = messageKeyFor(item.label_key) ?? statusKey(item.status);
              const last = index === timeline.length - 1;
              return (
                <li key={`${item.at}-${index}`} class="flex gap-4" aria-current={last ? 'step' : undefined}>
                  <div class="flex flex-col items-center">
                    <PaperStar now={last && !appealNow.value}>
                      <Pictogram name={statusIcon(item.status)} size={26} />
                    </PaperStar>
                    {last ? null : <span class="min-h-4 w-1 flex-1 rounded-full bg-primary/40" aria-hidden="true" />}
                  </div>
                  <div class="flex flex-col pb-5 pt-2">
                    <p class="text-lg font-semibold">{t(label)}</p>
                    <time dateTime={item.at} class="text-sm text-ink-muted">
                      {formatDate(item.at, code)}
                    </time>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {app.status === 'rejected' || app.status === 'approved' || app.status === 'paid' ? <AppealSection app={app} /> : null}

      <div class="mt-auto flex flex-col gap-3">
        {app.status === 'needs_proof' ? (
          <Button size="lg" icon="camera" block onClick={() => route('/proof')}>
            {t('result_add_proof')}
          </Button>
        ) : null}
        {app.status === 'on_hold_consent' ? (
          // Paused because permission was taken back: the consent centre can give it again.
          <Button size="lg" icon="retry" block onClick={() => route('/my-data')}>
            {t('mydata_again')}
          </Button>
        ) : null}
        <Button size="lg" variant="secondary" icon="person-help" block onClick={() => route('/ask')}>
          {t('ask_person')}
        </Button>
        <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')}>
          {t('go_home')}
        </Button>
      </div>
    </CitizenShell>
  );
}

/** "Ask a person": who can help, and the code to show them. Works offline once loaded. */
export function AskScreen() {
  const { loaded, reload } = useApplication(false);
  const { route } = useLocation();
  return (
    <WithApplication loaded={loaded} reload={reload}>
      {(app) => (
        <CitizenShell onBack={() => route('/')} prompt="ask_person_body">
          <div class="flex flex-col items-center gap-4 text-center">
            <Pictogram name="person-help" size={96} class="text-info-strong" />
            <h1 class="text-2xl font-bold">{t('ask_person_title')}</h1>
            <p class="text-lg text-ink">{t('ask_person_body')}</p>
          </div>
          <TrackingCode code={app.tracking_code} symbols={app.tracking_symbols ?? []} />
          <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')} class="mt-auto">
            {t('go_home')}
          </Button>
        </CitizenShell>
      )}
    </WithApplication>
  );
}

/** "We need one more paper": a photo of the proof, resized and uploaded like the card. */
export function ProofScreen() {
  const { loaded, reload } = useApplication(false);
  return (
    <WithApplication loaded={loaded} reload={reload}>
      {(app) => <Proof app={app} />}
    </WithApplication>
  );
}

function Proof({ app }: { app: ApplicationOut }) {
  const { route } = useLocation();
  const upload = usePhotoUpload(proofKindFor(app.decision), () => undefined, app.id);
  const { phase } = upload;
  const busy = phase.name === 'preparing' || phase.name === 'sending';
  const doc: DocumentView | null = phase.name === 'result' ? phase.doc : null;
  return (
    <CitizenShell onBack={busy ? undefined : () => route('/result')} prompt="result_needs_proof_title">
      <div class="flex items-center gap-4">
        <Pictogram name="document" size={64} class="text-primary" />
        <h1 class="text-2xl font-bold">{t('result_needs_proof_title')}</h1>
      </div>
      {app.decision?.explanation ? <ExplanationText explanation={app.decision.explanation} /> : null}
      <PhotoPreview
        source={upload.preview}
        busy={busy ? t(phase.name === 'sending' ? 'card_sending' : 'card_preparing') : undefined}
        label={t('result_add_proof')}
      />
      {phase.name === 'stored' ? <Notice tone="warn" icon="phone-saved" text={t('outbox_photo_saved')} /> : null}
      {phase.name === 'failed' ? <InlineFailure failure={phase.failure} /> : null}
      {phase.name === 'unreadable' ? <Notice tone="warn" icon="warning" text={t('card_read_failed')} /> : null}
      {doc && doc.accepted ? (
        <>
          <Notice tone="ok" icon="yes" text={t('result_proof_sent')} />
          <Button size="lg" icon="clock" block onClick={() => route('/track')} class="mt-auto">
            {t('home_see_application')}
          </Button>
        </>
      ) : (
        <>
          {doc ? <Notice tone="warn" icon="warning" text={t(messageKeyFor(doc.message_key) ?? 'card_read_failed')} /> : null}
          <div class="mt-auto">
            <PhotoButtons onFile={(file) => void upload.choose(file)} disabled={busy} takeLabel={doc ? 'card_retake' : 'card_take'} />
          </div>
        </>
      )}
    </CitizenShell>
  );
}
