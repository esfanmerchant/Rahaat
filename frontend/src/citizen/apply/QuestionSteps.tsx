import { useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { IncomeBand } from '../../shared/api/types';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { lang, t, type MessageKey } from '../../shared/i18n';
import { go, lazyRoute } from '../../shared/routing';
import { speechInputAvailable } from '../../shared/speechInput';
import type { VoiceAnswerProps, VoiceValue } from '../voice/VoiceAnswer';
import { answer, answerName, answerSpoken, draft, nextStep, stepPath, type AnswerField, type StepId, type Tri } from './flow';
import { AnswerButton, AnswerGroup, NextButton, Notice, numberKey, SaveStatus, sayKey, StepLayout } from './parts';

// Saying the answer is a lazy chunk; the pictures below it never wait for it.
const VoiceAnswer = lazyRoute<VoiceAnswerProps>(() => import('../voice/VoiceAnswer'));

function Voice(props: VoiceAnswerProps) {
  return speechInputAvailable() ? <VoiceAnswer {...props} /> : null;
}

function useNext(step: StepId): () => void {
  const { route } = useLocation();
  return () => {
    const d = draft.peek();
    if (d) go(route, stepPath(nextStep(d, step)));
  };
}

// ---- c. the name read from the card -----------------------------------------------------------

export function NameStep() {
  const next = useNext('name');
  const d = draft.value;
  const name = d?.cardName ?? '';
  const chosen = d?.nameAnswer;
  const code = lang.value;
  const speech = {
    id: `name:${name}:${code}`,
    // The name itself has no recording: a device voice reads it when one exists.
    items: [{ key: 'name_prompt', text: t('name_prompt', undefined, code) }, { key: 'name.dynamic', text: name }],
    lang: code,
  };
  const choose = (value: boolean): void => {
    answerName(value);
    sayKey(value ? 'answer_yes' : 'name_no_note');
  };
  return (
    <StepLayout step="name" speech={speech} icon="person" title={t('name_title')}>
      <p class="text-lg text-ink-muted">{t('name_prompt')}</p>
      {/* Read from the card: shown as text, never as HTML, in its own direction. */}
      <p class="rounded-lg border-2 border-line-strong bg-surface px-4 py-3 text-center text-3xl font-bold" dir="auto">
        <bdi>{name}</bdi>
      </p>
      <AnswerGroup>
        <AnswerButton icon="yes" label={t('answer_yes')} selected={chosen === true} onSelect={() => choose(true)} />
        <AnswerButton icon="no" label={t('answer_no')} selected={chosen === false} onSelect={() => choose(false)} tone="text-danger" />
      </AnswerGroup>
      {chosen === false ? <Notice tone="check" icon="person-help" text={t('name_no_note')} /> : null}
      {chosen === false ? <SaveStatus field="full_name" /> : null}
      <NextButton enabled={chosen !== undefined} onNext={next} />
    </StepLayout>
  );
}

// ---- d. people in the household ---------------------------------------------------------------

const MIN_PEOPLE = 1;
const MAX_PEOPLE = 20;

export function HouseholdStep() {
  const next = useNext('household');
  const saved = draft.value?.answers.household_size;
  const [count, setCount] = useState(saved ?? 1);
  // A confirmed spoken answer is already written (provenance spoken): Next must not write it again as tapped.
  const spokenCount = useRef<number | null>(null);

  const change = (delta: number): void => {
    const value = Math.min(MAX_PEOPLE, Math.max(MIN_PEOPLE, count + delta));
    setCount(value);
    const key = numberKey(value);
    if (key) sayKey(key);
  };
  const confirm = (): void => {
    if (spokenCount.current !== count) answer('household_size', count);
    next();
  };
  const spoken = (value: VoiceValue, confidence: number): void => {
    if (typeof value !== 'number') {
      spokenCount.current = null;
      answerSpoken('household_size', null, 0);
      return;
    }
    const people = Math.min(MAX_PEOPLE, Math.max(MIN_PEOPLE, Math.round(value)));
    setCount(people);
    spokenCount.current = people;
    answerSpoken('household_size', people, confidence);
  };

  const counterButton =
    'flex size-24 shrink-0 items-center justify-center rounded-full border-2 text-ink disabled:cursor-not-allowed disabled:border-line disabled:text-ink-subtle';
  return (
    <StepLayout step="household" prompt="household_prompt" icon="family" title={t('household_title')}>
      <p class="text-lg text-ink-muted">{t('household_prompt')}</p>
      <Voice question="household_size" expected="number" onAnswer={spoken} />
      {/* Numbers run left to right, as on a phone keypad, in every language. */}
      <div dir="ltr" class="flex items-center justify-between gap-3">
        <button
          type="button"
          class={`${counterButton} border-line-strong bg-paper hover:bg-surface`}
          disabled={count <= MIN_PEOPLE}
          onClick={() => change(-1)}
          aria-label={t('household_less')}
        >
          <Pictogram name="minus" size={56} />
        </button>
        <output aria-live="polite" class="rh-ltr text-center font-bold leading-none text-[4.5rem]" aria-label={t('household_people', { count })}>
          {count}
        </output>
        <button
          type="button"
          class={`${counterButton} border-primary bg-primary text-white hover:bg-primary-strong`}
          disabled={count >= MAX_PEOPLE}
          onClick={() => change(1)}
          aria-label={t('household_more')}
        >
          <Pictogram name="plus" size={56} />
        </button>
      </div>
      {/* One figure per person, so the number can be checked without reading it. */}
      <div class="flex flex-wrap justify-center gap-1 text-primary" aria-hidden="true">
        {Array.from({ length: count }, (_, index) => (
          <Pictogram key={index} name="person" size={28} />
        ))}
      </div>
      <SaveStatus field="household_size" />
      <NextButton enabled onNext={confirm} />
    </StepLayout>
  );
}

// ---- e. monthly income ------------------------------------------------------------------------

export const INCOME_BANDS: ReadonlyArray<{ value: IncomeBand; icon: PictogramName; label: MessageKey }> = [
  { value: 'under_15k', icon: 'income-1', label: 'income_under_15k' },
  { value: '15k_30k', icon: 'income-2', label: 'income_15k_30k' },
  { value: '30k_50k', icon: 'income-3', label: 'income_30k_50k' },
  { value: 'over_50k', icon: 'income-4', label: 'income_over_50k' },
];

export function IncomeStep() {
  const next = useNext('income');
  const chosen = draft.value?.answers.income_band;
  return (
    <StepLayout step="income" prompt="income_prompt" icon="payment" title={t('income_title')}>
      <Voice
        question="income_band"
        expected="income_band"
        onAnswer={(value, confidence) => {
          const band = INCOME_BANDS.find((item) => item.value === value);
          answerSpoken('income_band', band ? band.value : null, band ? confidence : 0);
        }}
      />
      <AnswerGroup>
        {INCOME_BANDS.map((band) => (
          <AnswerButton
            key={band.value}
            icon={band.icon}
            label={t(band.label)}
            selected={chosen === band.value}
            onSelect={() => {
              answer('income_band', band.value);
              sayKey(band.label);
            }}
          />
        ))}
      </AnswerGroup>
      <SaveStatus field="income_band" />
      <NextButton enabled={chosen !== undefined} onNext={next} />
    </StepLayout>
  );
}

// ---- f, g, h. yes, no, or I do not know -------------------------------------------------------

interface TriStepSpec {
  step: StepId;
  field: Extract<AnswerField, 'is_widow' | 'has_disability' | 'receives_other_aid'>;
  icon: PictogramName;
  title: MessageKey;
  prompt: MessageKey;
}

export const TRI_STEPS: Readonly<Record<'widow' | 'disability' | 'aid', TriStepSpec>> = {
  widow: { step: 'widow', field: 'is_widow', icon: 'widow', title: 'widow_title', prompt: 'widow_prompt' },
  disability: { step: 'disability', field: 'has_disability', icon: 'disability', title: 'disability_title', prompt: 'disability_prompt' },
  aid: { step: 'aid', field: 'receives_other_aid', icon: 'payment', title: 'aid_title', prompt: 'aid_prompt' },
};

export const TRI_ANSWERS: ReadonlyArray<{ value: Tri; icon: PictogramName; label: MessageKey; tone: string }> = [
  { value: true, icon: 'yes', label: 'answer_yes', tone: 'text-primary' },
  { value: false, icon: 'no', label: 'answer_no', tone: 'text-danger' },
  { value: null, icon: 'unknown', label: 'answer_unknown', tone: 'text-ink-muted' },
];

export function TriStep({ spec }: { spec: TriStepSpec }) {
  const next = useNext(spec.step);
  const chosen = draft.value?.answers[spec.field];
  return (
    <StepLayout step={spec.step} prompt={spec.prompt} icon={spec.icon} title={t(spec.title)}>
      <div class="flex justify-center">
        <Pictogram name={spec.icon} size={96} class="text-primary" />
      </div>
      <Voice
        question={spec.field}
        expected="yes_no"
        onAnswer={(value, confidence) => answerSpoken(spec.field, typeof value === 'boolean' ? value : null, typeof value === 'boolean' ? confidence : 0)}
      />
      <AnswerGroup>
        {TRI_ANSWERS.map((option) => (
          <AnswerButton
            key={String(option.value)}
            icon={option.icon}
            label={t(option.label)}
            tone={option.tone}
            selected={chosen !== undefined && chosen === option.value}
            onSelect={() => {
              answer(spec.field, option.value);
              sayKey(option.label);
            }}
          />
        ))}
      </AnswerGroup>
      <SaveStatus field={spec.field} />
      <NextButton enabled={chosen !== undefined} onNext={next} />
    </StepLayout>
  );
}
