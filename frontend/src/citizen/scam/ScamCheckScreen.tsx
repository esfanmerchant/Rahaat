import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { playSpeech } from '../../shared/audio';
import type { ApiFailure } from '../../shared/api/problem';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { lang, t, type MessageKey } from '../../shared/i18n';
import { online } from '../../shared/network';
import { speechInputAvailable, useSpeechInput } from '../../shared/speechInput';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure, Notice, sayKey } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { checkMessage, composeSender, composeSpoken, composeText } from './api';

const MAX_TEXT = 2000;

/** Words for a failed check: slow down (429), checker down (503), or the usual states. */
function checkFailureKey(failure: ApiFailure): MessageKey | null {
  if (failure.kind === 'rate_limited') return 'scam_too_many';
  if (failure.status === 503) return 'scam_unavailable';
  return null;
}

/**
 * The scam checker (PLAN D1.8): paste the message, or say it, and optionally
 * who sent it. One primary action: check it. Offline, the check waits and runs
 * by itself when the internet is back.
 */
export function ScamCheckScreen() {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const box = useRef<HTMLTextAreaElement>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const code = lang.value;
  const speech = useSpeechInput(code);
  const text = composeText.value;
  const canSpeak = speechInputAvailable();

  const say = (key: MessageKey): void => {
    setNotice(key);
    sayKey(key);
  };

  const send = async (): Promise<void> => {
    if (!composeText.peek().trim()) {
      say('scam_need_text');
      box.current?.focus();
      return;
    }
    setFailure(null);
    setNotice(null);
    if (!online.peek()) {
      setWaiting(true);
      sayKey('scam_waiting_offline');
      return;
    }
    setBusy(true);
    const result = await checkMessage(composeText.peek(), composeSender.peek(), composeSpoken.peek());
    setBusy(false);
    if (result.ok) {
      route(`/scam/answer/${result.data.report_id}`);
      return;
    }
    if (result.failure.kind === 'offline') {
      setWaiting(true);
      sayKey('scam_waiting_offline');
      return;
    }
    const key = checkFailureKey(result.failure);
    if (key) say(key);
    else setFailure(result.failure);
  };

  // Waiting for the network: check as soon as it is back.
  useEffect(() => {
    if (!waiting) return undefined;
    return online.subscribe((isOnline) => {
      if (!isOnline) return;
      setWaiting(false);
      void send();
    });
  }, [waiting]);

  // Read back what was heard, then ask the person to confirm it with an icon.
  const heard = speech.input.state === 'heard' ? speech.input.text : null;
  useEffect(() => {
    if (heard === null) return;
    playSpeech(
      `heard:${heard}`,
      [
        { key: 'scam_heard', text: t('scam_heard', undefined, code) },
        { key: 'heard.dynamic', text: heard },
      ],
      code,
    );
  }, [heard]);

  const failedWhy = speech.input.state === 'failed' ? speech.input.why : null;
  useEffect(() => {
    if (!failedWhy) return;
    const key: MessageKey =
      failedWhy === 'denied' ? 'scam_mic_denied' : failedWhy === 'unavailable' ? 'scam_mic_unavailable' : 'scam_mic_nothing';
    say(key);
  }, [failedWhy, speech.input]);

  const paste = async (): Promise<void> => {
    setNotice(null);
    try {
      const clip = await navigator.clipboard.readText();
      if (clip.trim()) {
        composeText.value = clip.slice(0, MAX_TEXT);
        composeSpoken.value = false;
        return;
      }
    } catch {
      // Not allowed or not supported: the person pastes into the box instead.
    }
    say('scam_paste_failed');
    box.current?.focus();
  };

  const useHeard = (): void => {
    if (heard === null) return;
    composeText.value = heard.slice(0, MAX_TEXT);
    composeSpoken.value = true;
    speech.reset();
  };

  const listening = speech.input.state === 'listening';
  return (
    <CitizenShell onBack={busy ? undefined : () => route('/')} prompt="scam_prompt">
      <div class="flex items-center gap-4">
        <Pictogram name="shield" size={64} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('scam_title')}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t('scam_prompt')}</p>
      <p class="flex items-center gap-2 rounded-lg border-2 border-warning bg-warning-soft p-2 text-base font-semibold text-warning-ink">
        <Pictogram name="warning" size={28} />
        <span class="flex-1">{t('scam_never_pay')}</span>
      </p>

      {heard !== null ? (
        <section aria-labelledby="scam-heard" class="flex flex-col gap-3 rounded-lg border-2 border-info bg-info-soft p-3">
          <h2 id="scam-heard" class="text-lg font-semibold text-info-strong">
            {t('scam_heard')}
          </h2>
          {/* What the recogniser heard, as text, in its own direction. */}
          <p dir="auto" class="rounded-md bg-paper p-2 text-lg text-ink">
            {heard}
          </p>
          <div class="grid grid-cols-2 gap-3">
            <Button size="lg" icon="yes" onClick={useHeard}>
              {t('scam_heard_yes')}
            </Button>
            <Button size="lg" variant="neutral" icon="no" onClick={speech.start}>
              {t('scam_heard_no')}
            </Button>
          </div>
        </section>
      ) : (
        <div class="flex flex-col gap-3">
          <Button size="lg" variant="secondary" icon="paste" block disabled={busy || listening} onClick={() => void paste()}>
            {t('scam_paste')}
          </Button>
          {canSpeak && failedWhy !== 'denied' && failedWhy !== 'unavailable' ? (
            listening ? (
              <Button size="lg" variant="primary" icon="microphone" block onClick={speech.stop} aria-pressed="true">
                {t('scam_stop_listening')}
              </Button>
            ) : (
              <Button size="lg" variant="secondary" icon="microphone" block disabled={busy} onClick={speech.start}>
                {t('scam_speak')}
              </Button>
            )
          ) : null}
          {listening ? (
            <p role="status" class="flex items-center gap-2 text-lg text-info-strong">
              <Pictogram name="microphone" size={32} class="motion-safe:animate-pulse" />
              <span class="flex-1">{t('scam_listening')}</span>
            </p>
          ) : null}
        </div>
      )}

      <div class="flex flex-col gap-2">
        <label for="scam-text" class="text-lg font-semibold">
          {t('scam_message_label')}
        </label>
        {/* The message is data: shown and sent as text, never as HTML. dir="auto" follows its own script. */}
        <textarea
          id="scam-text"
          ref={box}
          dir="auto"
          rows={6}
          maxLength={MAX_TEXT}
          value={text}
          disabled={busy}
          onInput={(event) => {
            composeText.value = (event.currentTarget as HTMLTextAreaElement).value;
            composeSpoken.value = false;
          }}
          class="min-h-tap w-full rounded-lg border-2 border-line-strong bg-paper p-3 text-lg text-ink"
        />
      </div>
      <div class="flex flex-col gap-2">
        <label for="scam-sender" class="text-base font-semibold text-ink-muted">
          {t('scam_sender_label')}
        </label>
        <input
          id="scam-sender"
          type="text"
          dir="auto"
          maxLength={64}
          autocomplete="off"
          value={composeSender.value}
          disabled={busy}
          onInput={(event) => {
            composeSender.value = (event.currentTarget as HTMLInputElement).value;
          }}
          class="min-h-tap w-full rounded-lg border-2 border-line-strong bg-paper px-3 text-lg text-ink"
        />
      </div>

      {notice ? (
        <Notice tone="warn" icon="warning" text={t(notice)}>
          <AudioPrompt prompt={notice} />
        </Notice>
      ) : null}
      {failure ? <InlineFailure failure={failure} /> : null}
      {waiting ? (
        <Notice tone="warn" icon="offline" text={t('scam_waiting_offline')}>
          <AudioPrompt prompt="scam_waiting_offline" />
        </Notice>
      ) : null}
      {busy ? (
        <p role="status" class="text-center text-lg text-ink-muted">
          {t('scam_checking')}
        </p>
      ) : null}

      <div class="mt-auto flex flex-col gap-3">
        <Button size="lg" icon="shield" block busy={busy} disabled={waiting} onClick={() => void send()}>
          {t('scam_check')}
        </Button>
        <Button size="md" variant="quiet" icon="clock" block disabled={busy} onClick={() => route('/scam/history')}>
          {t('scam_history')}
        </Button>
      </div>
    </CitizenShell>
  );
}
