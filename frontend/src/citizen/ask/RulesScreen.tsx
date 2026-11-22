import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { AskOut } from '../../shared/api/types';
import { playSpeech, unlockAudio, type SpeechItem, useServerSpeech } from '../../shared/audio';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { ScreenState } from '../../shared/components/ScreenState';
import { isLang, lang, t, type Key, type Lang } from '../../shared/i18n';
import '../../shared/i18n/more';
import { speechInputAvailable, useSpeechInput } from '../../shared/speechInput';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure, Notice } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';

const MAX_QUESTION = 500;

type Phase =
  | { name: 'compose' }
  | { name: 'asking' }
  | { name: 'answer'; out: AskOut }
  | { name: 'failed'; failure: ApiFailure };

/** The server's own language code, else ours. Server sentences carry their language and direction. */
function langOf(code: string): Lang {
  return isLang(code) ? code : lang.value;
}

function Answer({ out, onAgain }: { out: AskOut; onAgain: () => void }) {
  const { route } = useLocation();
  const code = langOf(out.lang);
  const ui = lang.value;
  const sentences = out.sentences;
  const after: SpeechItem[] = [];
  if (out.notice) after.push({ key: out.notice.key, text: out.notice.text, lang: langOf(out.notice.lang) });
  if (!out.answered && out.refusal) after.push({ key: out.refusal.key, text: out.refusal.text, lang: langOf(out.refusal.lang) });
  const speech = useServerSpeech({
    id: `ask:${out.decision.route}:${sentences.map((s) => s.text).join('|')}:${out.refusal?.key ?? ''}`,
    lang: code,
    clips: [],
    lines: sentences.map((s) => s.text),
    after,
    uiLang: ui,
  });
  const headingRef = useFocusOnMount<HTMLHeadingElement>();

  if (!out.answered) {
    const text = out.refusal?.text ?? t('rules_unavailable');
    return (
      <CitizenShell onBack={onAgain} speech={speech}>
        <div class="flex flex-col items-center gap-4 text-center">
          <Pictogram name="unknown" size={96} class="text-info-strong" />
          <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold" lang={code} dir={code === 'ur' ? 'rtl' : 'ltr'}>
            {text}
          </h1>
        </div>
        <Button size="lg" icon="person-help" block onClick={() => route('/ask')}>
          {t('ask_person')}
        </Button>
        <Button size="md" variant="neutral" icon="retry" block onClick={onAgain}>
          {t('rules_again')}
        </Button>
      </CitizenShell>
    );
  }

  return (
    <CitizenShell onBack={onAgain} speech={speech}>
      <div class="flex items-center gap-4">
        <Pictogram name="message" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('rules_answer')}
        </h1>
      </div>
      <ul class="flex flex-col gap-3">
        {sentences.map((sentence, index) => {
          const source = out.citations[sentence.citation];
          return (
            <li key={index} class="flex flex-col gap-1 rounded-lg border-2 border-line-strong bg-paper p-3">
              {/* The sentence is copied from the policy text: shown as text, in its own language. */}
              <p class="text-xl text-ink" lang={source ? langOf(source.lang) : code} dir={(source ? langOf(source.lang) : code) === 'ur' ? 'rtl' : 'ltr'}>
                {sentence.text}
              </p>
              {source ? (
                <p class="text-sm text-ink-muted" dir="auto">
                  {t('rules_source')}: {t('rules_source_line', { title: source.title, version: source.version, section: source.section })}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {out.notice ? (
        <div lang={langOf(out.notice.lang)} dir={langOf(out.notice.lang) === 'ur' ? 'rtl' : 'ltr'}>
          <Notice tone="check" icon="person-help" text={out.notice.text} />
        </div>
      ) : null}
      <Button size="lg" variant="secondary" icon="retry" block onClick={onAgain} class="mt-auto">
        {t('rules_again')}
      </Button>
    </CitizenShell>
  );
}

/** /rules: speak or type a question about the Rahat rules; answers are the policy's own sentences with their source. */
export default function RulesScreen() {
  const { route } = useLocation();
  const [phase, setPhase] = useState<Phase>({ name: 'compose' });
  const [text, setText] = useState('');
  const [empty, setEmpty] = useState(false);
  const speech = useSpeechInput(lang.value);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const listening = speech.input.state === 'listening';
  const micOk = speechInputAvailable();

  // What the phone heard goes into the box, is read back, and the Ask button is the confirmation.
  const heard = speech.input.state === 'heard' ? speech.input.text : null;
  useEffect(() => {
    if (!heard) return;
    setText(heard.slice(0, MAX_QUESTION));
    setEmpty(false);
    playSpeech(`rules-heard:${heard}`, [{ key: 'rules.heard', text: heard, lang: lang.peek() }], lang.peek());
  }, [heard]);

  const ask = async (): Promise<void> => {
    const question = text.trim();
    if (!question) {
      setEmpty(true);
      return;
    }
    setPhase({ name: 'asking' });
    const result = await call(api.POST('/v1/ask', { body: { question, lang: lang.peek() } }));
    setPhase(result.ok ? { name: 'answer', out: result.data } : { name: 'failed', failure: result.failure });
  };

  const again = (): void => {
    setText('');
    speech.reset();
    setPhase({ name: 'compose' });
  };

  if (phase.name === 'asking') {
    return (
      <CitizenShell>
        <ScreenState kind="loading" />
      </CitizenShell>
    );
  }
  if (phase.name === 'answer') return <Answer out={phase.out} onAgain={again} />;

  const failure = phase.name === 'failed' ? phase.failure : null;
  const failedText: Key | null = failure
    ? failure.kind === 'rate_limited'
      ? 'rules_limit'
      : failure.kind === 'server'
        ? 'rules_unavailable'
        : null
    : null;
  const micProblem: Key | null =
    speech.input.state === 'failed'
      ? speech.input.why === 'denied'
        ? 'voice_denied'
        : speech.input.why === 'unavailable'
          ? 'voice_unavailable'
          : 'voice_nothing'
      : !micOk
        ? 'voice_unavailable'
        : null;

  return (
    <CitizenShell onBack={() => route('/')} prompt="rules_prompt">
      <div class="flex items-center gap-4">
        <Pictogram name="message" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('home_rules')}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t('rules_prompt')}</p>

      {micOk ? (
        listening ? (
          <div class="flex flex-col gap-3">
            <p role="status" class="flex min-h-tap-lg items-center justify-center gap-3 rounded-lg border-2 border-primary bg-primary-soft px-3 text-xl font-semibold text-primary-strong">
              <Pictogram name="microphone" size={40} />
              {speech.input.state === 'listening' && speech.input.partial ? <span dir="auto">{speech.input.partial}</span> : t('voice_listening')}
            </p>
            <Button size="lg" variant="neutral" icon="pause" block onClick={speech.stop}>
              {t('scam_stop_listening')}
            </Button>
          </div>
        ) : (
          <Button
            size="lg"
            variant="secondary"
            icon="microphone"
            block
            onClick={() => {
              unlockAudio();
              speech.start();
            }}
          >
            {text ? t('voice_again') : t('rules_mic')}
          </Button>
        )
      ) : null}
      {micProblem && !listening ? <Notice tone="warn" icon="microphone" text={t(micProblem)} /> : null}

      <label class="flex flex-col gap-1 text-base font-semibold text-ink-muted">
        {t('rules_label')}
        <textarea
          value={text}
          rows={3}
          maxLength={MAX_QUESTION}
          onInput={(event) => {
            setText((event.target as HTMLTextAreaElement).value);
            setEmpty(false);
          }}
          dir="auto"
          class="min-h-tap-xl rounded-lg border-2 border-line-strong bg-paper px-3 py-2 text-xl font-normal text-ink"
        />
      </label>
      <p class="text-base text-ink-muted">{t('rules_example')}</p>
      {empty ? <Notice tone="warn" icon="warning" text={t('rules_empty_text')} /> : null}
      {failure ? (
        failedText ? (
          <Notice tone="warn" icon="warning" text={t(failedText)}>
            <AudioPrompt prompt={failedText} />
          </Notice>
        ) : (
          <InlineFailure failure={failure} />
        )
      ) : null}
      <Button size="lg" icon="yes" block disabled={listening} onClick={() => void ask()} class="mt-auto">
        {heard ? t('rules_heard_ok') : t('rules_ask')}
      </Button>
    </CitizenShell>
  );
}
