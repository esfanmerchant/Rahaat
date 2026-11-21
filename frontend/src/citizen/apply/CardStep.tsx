import { useLocation } from 'preact-iso';
import type { DocumentView } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { messageKeyFor, t, type MessageKey } from '../../shared/i18n';
import { draft, nextStep, setCard, stepPath } from './flow';
import { InlineFailure, NextButton, Notice, sayKey, StepLayout } from './parts';
import { PhotoButtons, PhotoPreview } from './PhotoParts';
import { usePhotoUpload } from './usePhotoUpload';

export const MAX_CARD_TRIES = 3;

/** The words for an upload result: the server's key when we know it, else one per quality. */
export function documentMessage(doc: DocumentView): MessageKey {
  if (doc.accepted) return messageKeyFor(doc.message_key) ?? 'doc_ok';
  return (
    messageKeyFor(doc.retake_hint) ??
    messageKeyFor(doc.message_key) ??
    messageKeyFor(`doc_retake_${doc.quality}`) ??
    'doc_retake_blurry'
  );
}

function isPersonWillCheck(doc: DocumentView): boolean {
  return doc.accepted && documentMessage(doc) === 'doc_person_will_check';
}

/**
 * b. Photo of the Rahat card. Resized on the device, uploaded, and the
 * server's quality check either accepts it or gives a retake hint, which is
 * spoken. After three tries the flow goes on: a person will help.
 */
export function CardStep() {
  const { route } = useLocation();
  const d = draft.value;

  const onResult = (doc: DocumentView): void => {
    const current = draft.peek();
    if (!current) return;
    if (doc.accepted) {
      setCard(isPersonWillCheck(doc) ? 'check' : 'accepted');
      sayKey(documentMessage(doc));
      return;
    }
    const tries = current.cardTries + 1;
    if (tries >= MAX_CARD_TRIES) {
      setCard('gave_up', tries);
      sayKey('card_give_up_body');
    } else {
      setCard('none', tries);
      sayKey(documentMessage(doc));
    }
  };

  const upload = usePhotoUpload('rahat_id', onResult);
  const { phase } = upload;
  const busy = phase.name === 'preparing' || phase.name === 'sending';
  const card = d?.card ?? 'none';
  const done = card !== 'none';
  const next = (): void => {
    const current = draft.peek();
    if (current) route(stepPath(nextStep(current, 'card')));
  };

  let body;
  if (busy) {
    body = upload.preview ? (
      <PhotoPreview source={upload.preview} busy={t(phase.name === 'sending' ? 'card_sending' : 'card_preparing')} label={t('card_title')} />
    ) : (
      <Notice tone="check" icon="clock" text={t('card_preparing')} />
    );
  } else if (phase.name === 'waiting') {
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <Notice tone="warn" icon="offline" text={t('card_waiting_offline')} />
      </>
    );
  } else if (phase.name === 'failed') {
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <InlineFailure failure={phase.failure}>
          <Button size="md" variant="neutral" icon="retry" onClick={() => void upload.retry()}>
            {t('retry')}
          </Button>
        </InlineFailure>
        <PhotoButtons onFile={(file) => void upload.choose(file)} takeLabel="card_retake" />
      </>
    );
  } else if (card === 'gave_up') {
    body = (
      <>
        <Notice tone="check" icon="person-help" text={t('card_give_up_title')}>
          <p class="text-lg">{t('card_give_up_body')}</p>
        </Notice>
        <NextButton enabled onNext={next} />
      </>
    );
  } else if (done) {
    const message: MessageKey = card === 'check' ? 'doc_person_will_check' : 'doc_ok';
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <Notice tone={card === 'check' ? 'check' : 'ok'} icon={card === 'check' ? 'person-help' : 'yes'} text={t(message)} />
        <NextButton enabled onNext={next} />
        <PhotoButtons onFile={(file) => void upload.choose(file)} takeLabel="card_retake" quiet />
      </>
    );
  } else if (phase.name === 'result' || phase.name === 'unreadable') {
    // Not accepted, or the photo could not be opened: say why and take it again.
    const message: MessageKey = phase.name === 'unreadable' ? 'card_read_failed' : documentMessage(phase.doc);
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <Notice tone="warn" icon="warning" text={t(message)} />
        <RetakeDots tries={d?.cardTries ?? 0} />
        <PhotoButtons onFile={(file) => void upload.choose(file)} takeLabel="card_retake" />
      </>
    );
  } else {
    body = (
      <>
        <div class="flex justify-center py-2">
          <Pictogram name="card" size={128} class="text-primary" />
        </div>
        <p class="text-lg text-ink-muted">{t('card_prompt')}</p>
        <div class="mt-auto">
          <PhotoButtons onFile={(file) => void upload.choose(file)} />
        </div>
      </>
    );
  }

  return (
    <StepLayout step="card" prompt="card_prompt" icon="camera" title={t('card_title')} busy={busy}>
      {body}
    </StepLayout>
  );
}

/** Three dots for the three tries, so the person sees how many are left. */
function RetakeDots({ tries }: { tries: number }) {
  return (
    <div class="flex items-center justify-center gap-3" aria-hidden="true">
      {Array.from({ length: MAX_CARD_TRIES }, (_, index) => (
        <span key={index} class={`block size-4 rounded-full ${index < tries ? 'bg-warning' : 'border-2 border-line-strong'}`} />
      ))}
    </div>
  );
}
