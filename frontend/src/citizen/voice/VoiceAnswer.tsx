import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { VoiceIn, VoiceOut } from '../../shared/api/types';
import { unlockAudio, useServerSpeech } from '../../shared/audio';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { isLang, lang, t, type Key, type Lang, type MessageKey } from '../../shared/i18n';
import '../../shared/i18n/more';
import { useSpeechInput } from '../../shared/speechInput';
import { draft } from '../apply/flow';
import { Notice, sayKey } from '../apply/parts';

export type VoiceQuestion = VoiceIn['question_key'];
export type VoiceValue = number | boolean | string | null;

export interface VoiceAnswerProps {
  question: Exclude<VoiceQuestion, 'full_name' | 'confirm'>;
  expected: Exclude<VoiceIn['expected'], 'name_confirm'>;
  /** The person confirmed the read-back: write the value (provenance `spoken`). */
  onAnswer: (value: VoiceValue, confidence: number) => void;
}

const BAND_ICON: Record<string, { icon: PictogramName; label: MessageKey }> = {
  under_15k: { icon: 'income-1', label: 'income_under_15k' },
  '15k_30k': { icon: 'income-2', label: 'income_15k_30k' },
  '30k_50k': { icon: 'income-3', label: 'income_30k_50k' },
  over_50k: { icon: 'income-4', label: 'income_over_50k' },
};

type Phase =
  | { name: 'idle' }
  | { name: 'checking' }
  | { name: 'confirm'; out: VoiceOut; heard: string }
  /** The server could not use the answer: what it said, and whether to go on with pictures only. */
  | { name: 'retry'; out: VoiceOut }
  | { name: 'done' };

function langOf(code: string): Lang {
  return isLang(code) ? code : lang.value;
}

/** What the person said, as a picture they can check without reading. */
function ConfirmPicture({ out, expected }: { out: VoiceOut; expected: VoiceAnswerProps['expected'] }) {
  if (expected === 'yes_no') {
    const icon: PictogramName = out.unknown || out.value === null ? 'unknown' : out.value === true ? 'yes' : 'no';
    return <Pictogram name={icon} size={72} class={icon === 'yes' ? 'text-primary' : icon === 'no' ? 'text-danger' : 'text-ink-muted'} />;
  }
  if (expected === 'income_band') {
    const band = typeof out.value === 'string' ? BAND_ICON[out.value] : undefined;
    return (
      <>
        <Pictogram name={band?.icon ?? 'unknown'} size={72} class="text-primary" />
        {band ? <span class="text-xl font-semibold">{t(band.label)}</span> : null}
      </>
    );
  }
  const count = typeof out.value === 'number' ? out.value : null;
  return count === null ? (
    <Pictogram name="unknown" size={72} class="text-ink-muted" />
  ) : (
    <>
      <span class="rh-ltr text-[4rem] font-bold leading-none">{count}</span>
      <span class="flex max-w-full flex-wrap justify-center gap-1 text-primary" aria-hidden="true">
        {Array.from({ length: Math.min(count, 20) }, (_, index) => (
          <Pictogram key={index} name="person" size={24} />
        ))}
      </span>
    </>
  );
}

/**
 * Say the answer instead of tapping it (D1.6). The phone's own recogniser
 * hears it; the transcript goes to POST /v1/voice/interpret with the question;
 * the answer is read back from the server's clips and shown as a picture, and
 * nothing is saved until the person confirms with the yes icon. The pictures
 * of the question stay available the whole time.
 */
export default function VoiceAnswer({ question, expected, onAnswer }: VoiceAnswerProps) {
  const speech = useSpeechInput(lang.value);
  const [phase, setPhase] = useState<Phase>({ name: 'idle' });
  const [blocked, setBlocked] = useState<Key | null>(null);
  const [problem, setProblem] = useState<Key | null>(null);
  const attempt = useRef(1);
  const pictures = phase.name === 'retry' && phase.out.fallback === 'use_pictures';
  const heard = speech.input.state === 'heard' ? speech.input.text : null;

  const interpret = async (transcript: string): Promise<void> => {
    setPhase({ name: 'checking' });
    setProblem(null);
    const applicationId = draft.peek()?.applicationId ?? undefined;
    const result = await call(
      api.POST('/v1/voice/interpret', {
        body: {
          question_key: question,
          expected,
          transcript,
          lang: lang.peek(),
          engine: 'device',
          attempt: attempt.current,
          ...(applicationId ? { application_id: applicationId } : {}),
        },
      }),
    );
    if (!result.ok) {
      setPhase({ name: 'idle' });
      const kind = result.failure.kind;
      const why: Key = kind === 'offline' || kind === 'network' ? 'voice_offline' : kind === 'rate_limited' ? 'voice_wait' : 'voice_error';
      setProblem(why);
      sayKey(why);
      return;
    }
    const out = result.data;
    if (out.form_patch && out.needs_confirmation) setPhase({ name: 'confirm', out, heard: transcript });
    else {
      attempt.current += 1;
      setPhase({ name: 'retry', out });
    }
  };

  useEffect(() => {
    if (heard) void interpret(heard);
  }, [heard]);

  // The recogniser failed: no permission or no support means pictures only; "nothing heard" is a second try.
  const failed = speech.input.state === 'failed' ? speech.input.why : null;
  useEffect(() => {
    if (!failed) return;
    if (failed === 'denied') setBlocked('voice_denied');
    else if (failed === 'unavailable') setBlocked('voice_unavailable');
    else {
      attempt.current += 1;
      setProblem('voice_nothing');
    }
    const key: Key = failed === 'denied' ? 'voice_denied' : failed === 'unavailable' ? 'voice_unavailable' : 'voice_nothing';
    sayKey(key);
  }, [failed]);

  const listen = (): void => {
    unlockAudio();
    setProblem(null);
    setPhase({ name: 'idle' });
    speech.start();
  };

  const confirmed = phase.name === 'confirm' ? phase : null;
  const readback = confirmed?.out.readback ?? null;
  const confirmSpeech = useServerSpeech(
    readback
      ? { id: `voice:${readback.text}`, lang: langOf(readback.lang), clips: readback.audio_keys, lines: [readback.text], uiLang: lang.value }
      : null,
  );
  const retryAsk = phase.name === 'retry' ? phase.out.ask_again : null;
  const retrySpeech = useServerSpeech(
    retryAsk ? { id: `voice-retry:${retryAsk.text}`, lang: langOf(retryAsk.lang), clips: retryAsk.audio_keys, lines: [retryAsk.text], uiLang: lang.value } : null,
  );

  const accept = (): void => {
    if (!confirmed?.out.form_patch) return;
    const entry = Object.values(confirmed.out.form_patch)[0];
    onAnswer(confirmed.out.unknown ? null : (entry?.value ?? null), entry?.confidence ?? 0);
    attempt.current = 1;
    setPhase({ name: 'done' });
    sayKey('voice_saved');
  };

  // Only pictures: the microphone is refused or missing.
  if (blocked) return <Notice tone="warn" icon="microphone" text={t(blocked)} />;

  if (speech.input.state === 'listening') {
    return (
      <div class="flex flex-col gap-3">
        <p role="status" class="flex min-h-tap-lg items-center justify-center gap-3 rounded-lg border-2 border-primary bg-primary-soft px-3 text-xl font-semibold text-primary-strong">
          <Pictogram name="microphone" size={40} />
          {speech.input.partial ? <span dir="auto">{speech.input.partial}</span> : t('voice_listening')}
        </p>
        <Button size="md" variant="neutral" icon="pause" block onClick={speech.stop}>
          {t('scam_stop_listening')}
        </Button>
      </div>
    );
  }

  if (phase.name === 'checking') {
    return (
      <p role="status" class="flex min-h-tap-lg items-center justify-center gap-3 rounded-lg border-2 border-line-strong bg-surface px-3 text-lg text-ink">
        {t('voice_checking')}
      </p>
    );
  }

  if (confirmed && readback) {
    return (
      <section aria-label={t('voice_heard')} class="flex flex-col gap-3 rounded-lg border-2 border-primary bg-paper p-3">
        <div class="flex items-start justify-between gap-2">
          <p class="text-base text-ink-muted" dir="auto">
            {t('voice_heard')}: <bdi>{confirmed.heard}</bdi>
          </p>
          <AudioPrompt speech={confirmSpeech} autoPlay class="shrink-0" />
        </div>
        <div class="flex flex-col items-center gap-2 text-center">
          <ConfirmPicture out={confirmed.out} expected={expected} />
          {/* The server's read-back sentence, in the language it was written in. */}
          <p class="text-2xl font-bold" lang={langOf(readback.lang)} dir={langOf(readback.lang) === 'ur' ? 'rtl' : 'ltr'}>
            {readback.text}
          </p>
        </div>
        <Button size="lg" icon="yes" block onClick={accept}>
          {t('voice_ok_yes')}
        </Button>
        <Button size="lg" variant="neutral" icon="no" block onClick={listen}>
          {t('scam_heard_no')}
        </Button>
      </section>
    );
  }

  return (
    <div class="flex flex-col gap-3">
      {phase.name === 'done' ? <Notice tone="ok" icon="yes" text={t('voice_saved')} /> : null}
      {phase.name === 'retry' && retryAsk ? (
        <Notice tone="warn" icon="warning" text={retryAsk.text}>
          <AudioPrompt speech={retrySpeech} autoPlay />
        </Notice>
      ) : null}
      {problem ? (
        <Notice tone="warn" icon="warning" text={t(problem)}>
          <AudioPrompt prompt={problem} />
        </Notice>
      ) : null}
      {pictures ? null : (
        <Button size="md" variant="secondary" icon="microphone" block onClick={listen}>
          {phase.name === 'retry' || problem === 'voice_nothing' ? t('voice_again') : t('voice_say')}
        </Button>
      )}
    </div>
  );
}
