import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { useServerSpeech, type SpeechItem } from '../../shared/audio';
import type { ApiFailure } from '../../shared/api/problem';
import type { ScamCheckOut } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { lang, t, type MessageKey } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure, Notice } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { askPerson, cachedAnswer, composeSender, composeSpoken, composeText, justDisputed, loadAnswer } from './api';
import { AnswerHeader, answerLang, isScamWarning, Links, Reasons, ReviewLine, reviewKey, Verified, WhatToDo } from './parts';

type Loaded = { state: 'loading' } | { state: 'failed'; failure: ApiFailure } | { state: 'ready'; answer: ScamCheckOut };

/** The answer for one report: from memory right after a check, otherwise from the server (and again on a language change). */
function useAnswer(id: string): { loaded: Loaded; reload: () => void } {
  const code = lang.value;
  const [attempt, setAttempt] = useState(0);
  const cached = cachedAnswer(id, code);
  const [loaded, setLoaded] = useState<Loaded>(cached ? { state: 'ready', answer: cached } : { state: 'loading' });
  useEffect(() => {
    const memory = cachedAnswer(id, code);
    if (memory && attempt === 0) {
      setLoaded({ state: 'ready', answer: memory });
      return undefined;
    }
    let live = true;
    setLoaded({ state: 'loading' });
    void loadAnswer(id).then((result) => {
      if (!live) return;
      setLoaded(result.ok ? { state: 'ready', answer: result.data } : { state: 'failed', failure: result.failure });
    });
    return () => {
      live = false;
    };
  }, [id, code, attempt]);
  return { loaded, reload: () => setAttempt((n) => n + 1) };
}

/** Which "ask a person" button fits the answer: none, the main one (not sure), or the "this is real" one. */
function askKind(answer: ScamCheckOut): 'none' | 'ask' | 'dispute' {
  if (!answer.can_dispute || answer.certainty === 'confirmed_real') return 'none';
  return isScamWarning(answer.certainty) ? 'dispute' : 'ask';
}

/**
 * The answer, for a person who cannot read: a large picture and colour for
 * how sure we are, the headline, reasons and what to do read aloud, links as
 * plain text with their warning, and "ask a person".
 */
export function ScamAnswerScreen({ id }: { id: string }) {
  const { route } = useLocation();
  const { loaded, reload } = useAnswer(id);
  const answer = loaded.state === 'ready' ? loaded.answer : null;
  const ui = lang.value;
  const thanked = justDisputed.value === id;
  const speech = useServerSpeech(
    answer
      ? {
          id: `scam:${answer.report_id}:${answer.lang}:${answer.review.status}:${thanked ? 'thanked' : ''}`,
          lang: answerLang(answer),
          clips: answer.audio_keys,
          lines: [answer.headline, ...answer.reasons.map((reason) => reason.text), answer.what_to_do],
          before: thanked ? [{ key: 'scam_dispute_sent', text: t('scam_dispute_sent', undefined, ui) }] : [],
          after: speechAfter(answer, ui),
          uiLang: ui,
        }
      : null,
  );
  const headingRef = useFocusOnMount<HTMLHeadingElement>(answer !== null);

  // The thank-you is said once; later visits only show the waiting state.
  useEffect(
    () => () => {
      if (justDisputed.peek() === id) justDisputed.value = null;
    },
    [id],
  );

  if (!answer) {
    return (
      <CitizenShell onBack={() => route('/scam')}>
        {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={reload} /> : <ScreenState kind="loading" />}
      </CitizenShell>
    );
  }

  const ask = askKind(answer);
  const another = (): void => {
    composeText.value = '';
    composeSender.value = '';
    composeSpoken.value = false;
    route('/scam');
  };
  return (
    <CitizenShell onBack={() => route('/scam')} speech={speech}>
      <AnswerHeader answer={answer} headingRef={headingRef} />
      {thanked ? <Notice tone="check" icon="person-help" text={t('scam_dispute_sent')} /> : null}
      {thanked ? null : <ReviewLine review={answer.review} />}
      <Verified answer={answer} />
      <WhatToDo answer={answer} />
      <Reasons answer={answer} />
      <Links answer={answer} />
      <div class="mt-auto flex flex-col gap-3 pt-2">
        {ask === 'ask' ? (
          <Button size="lg" icon="person-help" block onClick={() => route(`/scam/answer/${id}/ask`)}>
            {t('ask_person')}
          </Button>
        ) : null}
        <Button size="lg" variant={ask === 'ask' ? 'secondary' : 'primary'} icon="shield" block onClick={another}>
          {t('scam_check_another')}
        </Button>
        {ask === 'dispute' ? (
          <Button size="lg" variant="neutral" icon="person-help" block onClick={() => route(`/scam/answer/${id}/ask`)}>
            {t('scam_dispute')}
          </Button>
        ) : null}
        <Button size="md" variant="quiet" icon="clock" block onClick={() => route('/scam/history')}>
          {t('scam_history')}
        </Button>
        <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')}>
          {t('go_home')}
        </Button>
      </div>
    </CitizenShell>
  );
}

/** Our own clips after the server's words: the link warning, and the review status. */
function speechAfter(answer: ScamCheckOut, ui: 'ur' | 'en'): SpeechItem[] {
  const items: SpeechItem[] = [];
  if (answer.certainty === 'confirmed_real' && answer.verified?.genuine) {
    items.push({ key: 'scam_real_title', text: t('scam_real_title', undefined, ui) });
  }
  if (answer.urls.some((url) => url.risk !== 'low')) items.push({ key: 'scam_links_note', text: t('scam_links_note', undefined, ui) });
  const review = reviewKey(answer.review);
  if (review) items.push({ key: review, text: t(review, undefined, ui) });
  return items;
}

/** "Ask a person": confirm first, then open the case. The note is optional; nothing needs typing. */
export function ScamAskScreen({ id }: { id: string }) {
  const { route } = useLocation();
  const { loaded, reload } = useAnswer(id);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(loaded.state === 'ready');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const answer = loaded.state === 'ready' ? loaded.answer : null;

  if (!answer) {
    return (
      <CitizenShell onBack={() => route(`/scam/answer/${id}`)}>
        {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={reload} /> : <ScreenState kind="loading" />}
      </CitizenShell>
    );
  }
  const ask = askKind(answer);
  const send = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await askPerson(answer, note);
    setBusy(false);
    if (result.ok) route(`/scam/answer/${id}`, true);
    else setFailure(result.failure);
  };
  const title: MessageKey = ask === 'dispute' ? 'scam_dispute' : 'scam_dispute_title';
  return (
    <CitizenShell onBack={busy ? undefined : () => route(`/scam/answer/${id}`)} prompt="scam_dispute_body">
      <div class="flex items-center gap-4">
        <Pictogram name="person-help" size={64} class="text-info-strong" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t(title)}
        </h1>
      </div>
      <p class="text-lg text-ink">{t('scam_dispute_body')}</p>
      {ask === 'none' ? (
        // Asked already (or a real message): nothing to send again.
        <>
          <ReviewLine review={answer.review} />
          <Button size="lg" icon="back" block onClick={() => route(`/scam/answer/${id}`, true)} class="mt-auto">
            {t('back')}
          </Button>
        </>
      ) : (
        <>
          <div class="flex flex-col gap-2">
            <label for="scam-note" class="text-base font-semibold text-ink-muted">
              {t('scam_dispute_note')}
            </label>
            <textarea
              id="scam-note"
              dir="auto"
              rows={3}
              maxLength={500}
              value={note}
              disabled={busy}
              onInput={(event) => setNote((event.currentTarget as HTMLTextAreaElement).value)}
              class="min-h-tap w-full rounded-lg border-2 border-line-strong bg-paper p-3 text-lg text-ink"
            />
          </div>
          {failure ? <InlineFailure failure={failure} /> : null}
          <div class="mt-auto flex flex-col gap-3">
            <Button size="lg" icon="yes" block busy={busy} onClick={() => void send()}>
              {t('scam_dispute_yes')}
            </Button>
            <Button size="lg" variant="neutral" icon="no" block disabled={busy} onClick={() => route(`/scam/answer/${id}`)}>
              {t('scam_dispute_no')}
            </Button>
          </div>
        </>
      )}
    </CitizenShell>
  );
}
