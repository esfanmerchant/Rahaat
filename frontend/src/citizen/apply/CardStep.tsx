import { useLocation } from 'preact-iso';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { t, type MessageKey } from '../../shared/i18n';
import { go } from '../../shared/routing';
import { cardPhotoStored, documentMessage, draft, MAX_CARD_TRIES, nextStep, stepPath } from './flow';
import { InlineFailure, NextButton, Notice, sayKey, StepLayout } from './parts';
import { PhotoButtons, PhotoPreview } from './PhotoParts';
import { usePhotoUpload } from './usePhotoUpload';

export { documentMessage, MAX_CARD_TRIES };

/**
 * b. Photo of the Rahat card. Resized on the device and put in the outbox; the
 * server's quality check either accepts it or gives a retake hint, which is
 * spoken. After three tries the flow goes on: a person will help. Offline the
 * photo is saved on the phone and the person goes on; its answer comes later.
 */
export function CardStep() {
  const { route } = useLocation();
  const d = draft.value;

  // The draft already took the result (flow.ts); here it is only spoken.
  const onResult = (): void => {
    const current = draft.peek();
    if (!current) return;
    if (current.card === 'accepted' || current.card === 'check') {
      sayKey(current.card === 'check' ? 'doc_person_will_check' : 'doc_ok');
    } else if (current.card === 'gave_up') {
      sayKey('card_give_up_body');
    } else if (current.cardHint) {
      sayKey(current.cardHint);
    }
  };

  const upload = usePhotoUpload('rahat_id', onResult);
  const { phase } = upload;
  const busy = phase.name === 'preparing' || phase.name === 'sending';
  const card = d?.card ?? 'none';
  const next = (): void => {
    const current = draft.peek();
    if (current) go(route, stepPath(nextStep(current, 'card')));
  };
  const take = (file: File | undefined): void => void upload.choose(file);

  let body;
  if (busy) {
    body = upload.preview ? (
      <PhotoPreview source={upload.preview} busy={t(phase.name === 'sending' ? 'card_sending' : 'card_preparing')} label={t('card_title')} />
    ) : (
      <Notice tone="check" icon="clock" text={t('card_preparing')} />
    );
  } else if (phase.name === 'failed') {
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <InlineFailure failure={phase.failure}>
          <Button size="md" variant="neutral" icon="retry" onClick={upload.retry}>
            {t('retry')}
          </Button>
        </InlineFailure>
        <PhotoButtons onFile={take} takeLabel="card_retake" />
      </>
    );
  } else if (card === 'queued') {
    // Saved on this phone: the person can go on; the answer comes when the network is back.
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        {cardPhotoStored() === false ? (
          <Notice tone="warn" icon="offline" text={t('card_waiting_offline')} />
        ) : (
          <Notice tone="warn" icon="phone-saved" text={t('outbox_photo_saved')} />
        )}
        <NextButton enabled onNext={next} />
        <PhotoButtons onFile={take} takeLabel="card_retake" quiet />
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
  } else if (card === 'accepted' || card === 'check') {
    const message: MessageKey = card === 'check' ? 'doc_person_will_check' : 'doc_ok';
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <Notice tone={card === 'check' ? 'check' : 'ok'} icon={card === 'check' ? 'person-help' : 'yes'} text={t(message)} />
        <NextButton enabled onNext={next} />
        <PhotoButtons onFile={take} takeLabel="card_retake" quiet />
      </>
    );
  } else if (phase.name === 'unreadable' || d?.cardHint) {
    // Not accepted, or the photo could not be opened: say why and take it again.
    const message: MessageKey = phase.name === 'unreadable' ? 'card_read_failed' : (d?.cardHint ?? 'doc_retake_blurry');
    body = (
      <>
        <PhotoPreview source={upload.preview} label={t('card_title')} />
        <Notice tone="warn" icon="warning" text={t(message)} />
        <RetakeDots tries={d?.cardTries ?? 0} />
        <PhotoButtons onFile={take} takeLabel="card_retake" />
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
          <PhotoButtons onFile={take} />
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
