import type { ComponentChildren } from 'preact';
import { useEffect } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { playPrompt } from '../../shared/audio';
import type { ApiFailure } from '../../shared/api/problem';
import type { Speech } from '../../shared/components/AudioPrompt';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { Spinner } from '../../shared/components/Spinner';
import { lang, t, type Key, type MessageKey } from '../../shared/i18n';
import { go } from '../../shared/routing';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { CitizenShell } from '../CitizenShell';
import { draft, fieldState, flush, previousStep, STEPS, stepPath, type SavedField, type SaveState, type StepId } from './flow';

/** Spoken numbers: digit_0..9 and count_10..20. */
export function numberKey(n: number): MessageKey | null {
  if (Number.isInteger(n) && n >= 0 && n <= 9) return `digit_${n}` as MessageKey;
  if (Number.isInteger(n) && n >= 10 && n <= 20) return `count_${n}` as MessageKey;
  return null;
}

/** Read an answer back as soon as it is tapped. */
export function sayKey(key: Key): void {
  const code = lang.peek();
  playPrompt(key, code, t(key, undefined, code));
}

/** A small eight-point star: finished steps are filled, the current one is gold with a ring, the next ones are outlined. */
function MiniStar({ state }: { state: 'done' | 'current' | 'next' }) {
  const size = state === 'current' ? 26 : 20;
  return (
    <span class="relative grid shrink-0 place-items-center" aria-hidden="true">
      {state === 'current' ? <span class="absolute size-6 rounded-full bg-noor/50 hidden motion-safe:block motion-safe:animate-ring" /> : null}
      <svg viewBox="0 0 24 24" width={size} height={size} class="relative">
        <g
          fill={state === 'done' ? '#0b6a46' : state === 'current' ? '#ffd36e' : 'none'}
          stroke={state === 'done' ? '#0b6a46' : state === 'current' ? '#b8860b' : '#6c6880'}
          stroke-width="2"
          stroke-linejoin="round"
        >
          <rect x="5" y="5" width="14" height="14" />
          <rect x="5" y="5" width="14" height="14" transform="rotate(45 12 12)" />
        </g>
      </svg>
    </span>
  );
}

export function ProgressDots({ step }: { step: StepId }) {
  const index = STEPS.indexOf(step);
  const total = STEPS.length;
  return (
    <div
      role="progressbar"
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={index + 1}
      aria-label={t('apply_progress', { current: index + 1, total })}
      class="flex items-center justify-center gap-1.5 py-1"
    >
      {STEPS.map((id, i) => (
        <MiniStar key={id} state={i === index ? 'current' : i < index ? 'done' : 'next'} />
      ))}
    </div>
  );
}

interface StepLayoutProps {
  step: StepId;
  prompt?: MessageKey;
  speech?: Speech;
  icon: PictogramName;
  title: string;
  /** Hide the back button while a request runs. */
  busy?: boolean;
  children?: ComponentChildren;
}

/** Shared frame of every question: back, speaker, progress dots, pictogram and the question. */
export function StepLayout({ step, prompt, speech, icon, title, busy = false, children }: StepLayoutProps) {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const d = draft.value;
  const back = (): void => {
    const previous = d ? previousStep(d, step) : null;
    go(route, previous ? stepPath(previous) : '/', 'back');
  };
  return (
    <CitizenShell onBack={busy ? undefined : back} prompt={prompt} speech={speech} progress={<ProgressDots step={step} />} pane={{ kind: 'apply', step }}>
      <div class="flex items-center gap-4">
        <span class="grid size-20 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
          <Pictogram name={icon} size={56} />
        </span>
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold lg:text-[1.75rem]">
          {title}
        </h1>
      </div>
      {children}
    </CitizenShell>
  );
}

interface AnswerButtonProps {
  icon: PictogramName;
  label: string;
  selected: boolean;
  onSelect: () => void;
  /** Colour of the pictogram. */
  tone?: string;
  disabled?: boolean;
  lang?: string;
}

/** A large pictogram answer. Part of a radiogroup; the chosen one shows a tick. */
export function AnswerButton({ icon, label, selected, onSelect, tone = 'text-primary', disabled = false, lang: code }: AnswerButtonProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      class={
        'rh-tile flex min-h-tap-lg w-full items-center gap-3 rounded-xl border-2 px-3 py-2 text-start text-xl font-semibold lg:min-h-40 lg:flex-col lg:justify-center lg:gap-3 lg:rounded-2xl lg:px-4 lg:py-5 lg:text-center ' +
        (selected
          ? 'rh-select border-primary bg-primary-soft text-primary-strong'
          : 'border-line-strong bg-paper text-ink hover:bg-surface active:bg-surface')
      }
    >
      <span class="relative shrink-0">
        <Pictogram name={icon} size={56} class={selected ? 'text-primary-strong' : tone} />
        {/* The chosen answer gets a tick on its picture, not only a colour. */}
        {selected ? (
          <span class="absolute -end-2 -top-2 rounded-full bg-paper text-primary motion-safe:animate-pop">
            <Pictogram name="yes" size={26} />
          </span>
        ) : null}
      </span>
      <span class="min-w-0 flex-1" lang={code}>
        {label}
      </span>
    </button>
  );
}

export function AnswerGroup({ labelledBy, children }: { labelledBy?: string; children?: ComponentChildren }) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} class="flex flex-col gap-3 lg:grid lg:grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] lg:gap-4 lg:has-[>:nth-child(4):last-child]:grid-cols-2">
      {children}
    </div>
  );
}

/** The step's primary action. */
export function NextButton({ enabled, onNext, busy = false }: { enabled: boolean; onNext: () => void; busy?: boolean }) {
  return (
    <Button size="lg" icon="forward" block disabled={!enabled} busy={busy} onClick={onNext} class="mt-auto">
      {t('next')}
    </Button>
  );
}

/**
 * How each per-answer state looks: saved on this phone (sealed), not sent yet
 * (memory only, no PIN key), sending, sent, or failed.
 */
export const SAVE_SPEC: Record<SaveState, { icon: PictogramName | null; key: MessageKey; tone: string }> = {
  stored: { icon: 'phone-saved', key: 'outbox_stored', tone: 'text-warning-ink' },
  waiting: { icon: 'clock', key: 'apply_waiting', tone: 'text-warning-ink' },
  sending: { icon: null, key: 'outbox_sending', tone: 'text-ink-muted' },
  sent: { icon: 'yes', key: 'outbox_sent', tone: 'text-primary-strong' },
  failed: { icon: 'warning', key: 'apply_save_failed', tone: 'text-danger' },
};

/** Per-answer status: saved on this phone, sending, sent, or failed with a retry. */
export function SaveStatus({ field }: { field: SavedField }) {
  const status = fieldState(field);
  if (!status) return <p class="min-h-tap" aria-hidden="true" />;
  const { icon, tone } = SAVE_SPEC[status.state];
  const key = status.why ?? SAVE_SPEC[status.state].key;
  return (
    <div role="status" class={`flex min-h-tap items-center gap-2 text-base ${tone}`}>
      {icon ? <Pictogram name={icon} size={28} /> : <Spinner size={24} />}
      <span class="flex-1">{t(key)}</span>
      {status.state === 'failed' && key === 'apply_save_failed' ? (
        <Button size="md" variant="neutral" icon="retry" onClick={() => void flush()}>
          {t('retry')}
        </Button>
      ) : null}
    </div>
  );
}

export function failureKey(failure: ApiFailure): MessageKey {
  switch (failure.kind) {
    case 'offline':
      return 'state_offline_body';
    case 'forbidden':
      return 'state_denied_body';
    case 'conflict':
      return failure.problem?.code === 'consent_required' ? 'apply_need_consent' : 'state_error_body';
    default:
      return 'state_error_body';
  }
}

/** A failed action shown in place, spoken once, with the reference for a helper. */
export function InlineFailure({ failure, children }: { failure: ApiFailure; children?: ComponentChildren }) {
  const key = failureKey(failure);
  useEffect(() => sayKey(key), [key, failure]);
  const offline = failure.kind === 'offline';
  return (
    <div
      role="alert"
      class={`flex items-start gap-3 rounded-lg border-2 p-3 ${offline ? 'border-ink bg-surface text-ink' : 'border-danger bg-danger-soft text-danger'}`}
    >
      <Pictogram name={offline ? 'offline' : 'warning'} size={36} />
      <div class="flex flex-1 flex-col items-start gap-2">
        <p class="text-lg font-semibold">{t(key)}</p>
        {failure.problem?.request_id ? (
          <p class="text-sm">{t('state_reference', { id: failure.problem.request_id })}</p>
        ) : null}
        <AudioPrompt prompt={key} />
        {children}
      </div>
    </div>
  );
}

/** A spoken message box: tone ok (green), check (blue, a person will look), warn (amber). */
export function Notice({ tone, icon, text, children }: { tone: 'ok' | 'check' | 'warn'; icon: PictogramName; text: string; children?: ComponentChildren }) {
  const box = {
    ok: 'border-primary bg-primary-soft text-primary-strong',
    check: 'border-info bg-info-soft text-info-strong',
    warn: 'border-warning bg-warning-soft text-warning-ink',
  }[tone];
  return (
    <div role="status" class={`flex items-start gap-3 rounded-lg border-2 p-3 ${box}`}>
      <Pictogram name={icon} size={40} />
      <div class="flex flex-1 flex-col items-start gap-2">
        <p class="text-lg font-semibold">{text}</p>
        {children}
      </div>
    </div>
  );
}
