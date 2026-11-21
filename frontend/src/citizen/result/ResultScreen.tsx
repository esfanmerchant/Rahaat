import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { audioKeys, type SpeechItem } from '../../shared/audio';
import type { DecisionOutcome, DecisionUserView, Explanation } from '../../shared/api/types';
import type { Speech } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram, pictogramFor, type PictogramName } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { dirOf, isLang, lang, t, type Lang, type MessageKey } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { lastSubmit } from '../apply/flow';
import { CitizenShell } from '../CitizenShell';
import { useApplication } from './data';

type Tone = 'ok' | 'warn' | 'check' | 'neutral';

const OUTCOMES: Record<DecisionOutcome | 'pending', { title: MessageKey; icon: PictogramName; tone: Tone }> = {
  approved: { title: 'result_approved_title', icon: 'yes', tone: 'ok' },
  needs_proof: { title: 'result_needs_proof_title', icon: 'document', tone: 'warn' },
  needs_human: { title: 'result_needs_human_title', icon: 'person-help', tone: 'check' },
  rejected: { title: 'result_rejected_title', icon: 'no', tone: 'neutral' },
  pending: { title: 'result_pending_title', icon: 'clock', tone: 'check' },
};

const TONE_CLASS: Record<Tone, string> = {
  ok: 'border-primary bg-primary-soft text-primary-strong',
  warn: 'border-warning bg-warning-soft text-warning-ink',
  check: 'border-info bg-info-soft text-info-strong',
  neutral: 'border-line-strong bg-surface text-ink',
};

/** The language the server wrote the explanation in (falls back to the UI language). */
function explanationLang(explanation: Explanation | undefined, fallback: Lang): Lang {
  return explanation && isLang(explanation.lang) ? explanation.lang : fallback;
}

/**
 * Spoken explanation: the server's pre-generated clips when every one of them
 * exists, otherwise its sentences read by a device voice. `undefined` while
 * the list of recordings loads.
 */
export function useExplanationSpeech(decision: DecisionUserView | null | undefined, title: MessageKey): Speech | undefined {
  const ui = lang.value;
  const explanation = decision?.explanation;
  const spoken = explanationLang(explanation, ui);
  const [files, setFiles] = useState<Set<string> | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    void audioKeys(spoken).then((keys) => {
      if (live) setFiles(keys);
    });
    return () => {
      live = false;
    };
  }, [spoken]);
  if (files === undefined) return undefined;
  const items: SpeechItem[] = [{ key: title, text: t(title, undefined, ui) }];
  if (explanation) {
    const clips = explanation.audio_keys ?? [];
    if (clips.length > 0 && files !== null && clips.every((key) => files.has(key))) {
      for (const key of clips) items.push({ key, lang: spoken });
    } else {
      const lines = [...explanation.sentences, ...(explanation.next_step ? [explanation.next_step] : [])];
      lines.forEach((text, index) => items.push({ key: `explanation.${index}`, text, lang: spoken }));
    }
  } else {
    items.push({ key: 'result_pending_body', text: t('result_pending_body', undefined, ui) });
  }
  return { id: `result:${decision?.decision_id ?? 'pending'}:${ui}:${files ? 'files' : 'voice'}`, items, lang: ui };
}

/** The server's sentences and next step, as text (never HTML), in the language they were written in. */
export function ExplanationText({ explanation }: { explanation: Explanation }) {
  const code = explanationLang(explanation, lang.value);
  return (
    <div lang={code} dir={dirOf(code)} class="flex flex-col gap-3">
      {explanation.sentences.map((sentence, index) => (
        <p key={index} class="text-lg text-ink">
          {sentence}
        </p>
      ))}
      {explanation.next_step ? (
        <div class="rounded-lg border-2 border-line bg-surface p-3">
          <p class="text-base font-semibold text-ink-muted" lang={lang.value} dir={dirOf(lang.value)}>
            {t('result_next')}
          </p>
          <p class="text-lg text-ink">{explanation.next_step}</p>
        </div>
      ) : null}
    </div>
  );
}

/** Which proof the person is asked for; the server should name it (docs/REQUESTS.md). */
export function proofKindFor(decision: DecisionUserView | null | undefined): 'income_proof' | 'other' {
  const codes = decision?.explanation.reason_codes ?? [];
  return codes.some((code) => code.toUpperCase().includes('INCOME')) ? 'income_proof' : 'other';
}

/**
 * The result after Send (PLAN D1.4), driven by decision.outcome and
 * decision.explanation from the server. Plain words, never scores.
 */
export function ResultScreen() {
  const { route } = useLocation();
  const { loaded, reload } = useApplication(false);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(loaded.state === 'ready');
  const recent = lastSubmit.value;
  const app = loaded.state === 'ready' ? loaded.app : null;
  // Right after Send the submit response carries the decision; later the application does.
  const decision = (recent && app && recent.application.id === app.id ? recent.decision : null) ?? app?.decision ?? null;
  const spec = OUTCOMES[decision?.outcome ?? 'pending'];
  const speech = useExplanationSpeech(decision, spec.title);

  if (loaded.state === 'loading') {
    return (
      <CitizenShell onBack={() => route('/')}>
        <ScreenState kind="loading" />
      </CitizenShell>
    );
  }
  if (loaded.state === 'failed') {
    return (
      <CitizenShell onBack={() => route('/')}>
        <FailureState failure={loaded.failure} onRetry={reload} />
      </CitizenShell>
    );
  }
  if (loaded.state === 'empty' || !app) {
    return (
      <CitizenShell onBack={() => route('/')}>
        <ScreenState kind="empty" title={t('track_empty_title')} body={t('track_empty_body')}>
          <Button size="lg" icon="document" block onClick={() => route('/apply')}>
            {t('home_apply')}
          </Button>
        </ScreenState>
      </CitizenShell>
    );
  }

  const icon = pictogramFor(decision?.explanation.pictogram) ?? spec.icon;
  const outcome = decision?.outcome;
  return (
    <CitizenShell onBack={() => route('/')} speech={speech}>
      <div class="flex flex-col items-center gap-4 text-center">
        <span class={`flex size-32 items-center justify-center rounded-full border-4 ${TONE_CLASS[spec.tone]}`}>
          <Pictogram name={icon} size={88} />
        </span>
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t(spec.title)}
        </h1>
      </div>
      {decision ? (
        <ExplanationText explanation={decision.explanation} />
      ) : (
        <p class="text-lg text-ink">{t('result_pending_body')}</p>
      )}
      <div class="mt-auto flex flex-col gap-3">
        {outcome === 'needs_proof' ? (
          <Button size="lg" icon="camera" block onClick={() => route('/proof')}>
            {t('result_add_proof')}
          </Button>
        ) : (
          <Button size="lg" icon="clock" block onClick={() => route('/track')}>
            {t('home_see_application')}
          </Button>
        )}
        {decision?.explanation.ask_a_person !== false ? (
          <Button size="lg" variant="secondary" icon="person-help" block onClick={() => route('/ask')}>
            {t('ask_person')}
          </Button>
        ) : null}
        {outcome === 'needs_proof' ? (
          <Button size="md" variant="quiet" icon="clock" block onClick={() => route('/track')}>
            {t('home_see_application')}
          </Button>
        ) : null}
        <Button size="md" variant="quiet" icon="home" block onClick={() => route('/')}>
          {t('go_home')}
        </Button>
      </div>
    </CitizenShell>
  );
}
