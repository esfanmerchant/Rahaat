import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { SpeechItem } from '../../shared/audio';
import type { ApiFailure } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { lang, t, type Lang, type MessageKey } from '../../shared/i18n';
import { online } from '../../shared/network';
import {
  consentNeeded,
  draft,
  fieldState,
  queuedSubmit,
  setReturnToReview,
  stepPath,
  submitApplication,
  type Draft,
  type SavedField,
  type StepId,
} from './flow';
import { INCOME_BANDS, TRI_ANSWERS, TRI_STEPS } from './QuestionSteps';
import { InlineFailure, Notice, numberKey, SAVE_SPEC, sayKey, StepLayout } from './parts';

interface Row {
  step: StepId;
  icon: PictogramName;
  label: MessageKey;
  /** What is shown; `valueKey` is what is spoken (null: read `value` with a device voice). */
  value: string;
  valueKey: MessageKey | null;
  valueIcon?: PictogramName;
  field?: SavedField;
}

function rows(d: Draft, code: Lang): Row[] {
  const list: Row[] = [];
  const cardKey: MessageKey = d.card === 'accepted' ? 'review_card_ok' : d.card === 'queued' ? 'outbox_stored' : 'review_card_check';
  list.push({
    step: 'card',
    icon: 'card',
    label: 'review_card',
    value: t(cardKey, undefined, code),
    valueKey: cardKey,
    valueIcon: d.card === 'accepted' ? 'yes' : d.card === 'queued' ? 'phone-saved' : 'person-help',
  });
  if (d.cardName) {
    list.push({
      step: 'name',
      icon: 'person',
      label: 'review_name',
      value: d.nameAnswer === false ? t('name_no_note', undefined, code) : d.cardName,
      valueKey: d.nameAnswer === false ? 'name_no_note' : null,
      field: 'full_name',
    });
  }
  const size = d.answers.household_size;
  list.push({
    step: 'household',
    icon: 'family',
    label: 'review_household',
    value: size === undefined ? t('review_not_answered', undefined, code) : String(size),
    valueKey: size === undefined ? 'review_not_answered' : numberKey(size),
    field: 'household_size',
  });
  const band = INCOME_BANDS.find((item) => item.value === d.answers.income_band);
  list.push({
    step: 'income',
    icon: 'payment',
    label: 'review_income',
    value: t(band?.label ?? 'review_not_answered', undefined, code),
    valueKey: band?.label ?? 'review_not_answered',
    ...(band ? { valueIcon: band.icon } : {}),
    field: 'income_band',
  });
  const tri: ReadonlyArray<[keyof typeof TRI_STEPS, MessageKey]> = [
    ['widow', 'step_widow'],
    ['disability', 'review_disability'],
    ['aid', 'step_aid'],
  ];
  for (const [step, label] of tri) {
    const spec = TRI_STEPS[step];
    const value = d.answers[spec.field];
    const option = value === undefined ? undefined : TRI_ANSWERS.find((item) => item.value === value);
    list.push({
      step,
      icon: spec.icon,
      label,
      value: t(option?.label ?? 'review_not_answered', undefined, code),
      valueKey: option?.label ?? 'review_not_answered',
      ...(option ? { valueIcon: option.icon } : {}),
      field: spec.field,
    });
  }
  return list;
}

/** i. Review: the answers as icons, read aloud, then one Submit. */
export function ReviewStep() {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const d = draft.value;
  const code = lang.value;
  // Back on the review after a "Change": the next answers follow the normal order again.
  useEffect(() => {
    if (draft.peek()?.returnToReview) setReturnToReview(false);
  }, []);
  if (!d) return null;
  const list = rows(d, code);

  const items: SpeechItem[] = [{ key: 'review_prompt', text: t('review_prompt', undefined, code) }];
  for (const row of list) {
    items.push({ key: row.label, text: t(row.label, undefined, code) });
    items.push(row.valueKey ? { key: row.valueKey, text: t(row.valueKey, undefined, code) } : { key: 'name.dynamic', text: row.value });
  }
  const speech = { id: `review:${list.map((row) => row.value).join('|')}:${code}`, items, lang: code };

  const change = (step: StepId): void => {
    setReturnToReview(true);
    route(stepPath(step));
  };

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    const result = await submitApplication();
    setBusy(false);
    if (result.ok && result.data) {
      route('/result', true);
      return;
    }
    if (result.ok) {
      sayKey('outbox_submit_saved'); // kept on the phone; sent when the network is back
      return;
    }
    if (consentNeeded.peek()) {
      route(stepPath('consent'));
      return;
    }
    setFailure(result.failure);
  };

  const waiting = queuedSubmit() !== null;
  const offline = !online.value;
  return (
    // While Send waits for the network the person can still go back; it is sent when the network returns.
    <StepLayout step="review" speech={speech} icon="document" title={t('review_title')} busy={busy && !waiting}>
      <p class="text-lg text-ink-muted">{t('review_prompt')}</p>
      <ul class="flex flex-col gap-2">
        {list.map((row) => (
          <ReviewRow key={row.step} row={row} onChange={() => change(row.step)} disabled={busy} />
        ))}
      </ul>
      {failure ? <InlineFailure failure={failure} /> : null}
      {waiting || (busy && offline) ? <Notice tone="warn" icon="phone-saved" text={t('outbox_submit_saved')} /> : null}
      {busy && !waiting && !offline ? (
        <p role="status" class="text-center text-lg text-ink-muted">
          {t('submit_sending')}
        </p>
      ) : null}
      <Button size="lg" icon="forward" block busy={busy} onClick={() => void submit()} class="mt-auto">
        {t('submit')}
      </Button>
    </StepLayout>
  );
}

function ReviewRow({ row, onChange, disabled }: { row: Row; onChange: () => void; disabled: boolean }) {
  const saved = row.field ? fieldState(row.field) : undefined;
  const state = saved?.state;
  const spec = state && state !== 'sent' && state !== 'sending' ? SAVE_SPEC[state] : null;
  const status: { icon: PictogramName; tone: string; key: MessageKey } | null = spec
    ? { icon: spec.icon ?? 'clock', tone: spec.tone, key: saved?.why ?? spec.key }
    : null;
  return (
    <li class="flex items-start gap-3 rounded-lg border-2 border-line bg-surface p-2">
      <Pictogram name={row.icon} size={44} class="mt-1 text-primary" />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <div class="flex items-center justify-between gap-2">
          <span class="flex items-center gap-1 text-base font-semibold text-ink-muted">
            {t(row.label)}
            {state === 'sent' ? <Pictogram name="yes" size={20} label={t('outbox_sent')} class="text-primary" /> : null}
          </span>
          <button
            type="button"
            onClick={onChange}
            disabled={disabled}
            class="inline-flex min-h-tap min-w-tap shrink-0 items-center justify-center gap-1 rounded-md border-2 border-line-strong bg-paper px-2 text-base font-semibold text-ink hover:bg-sunken"
          >
            <Pictogram name="edit" size={22} />
            <span>{t('review_change')}</span>
          </button>
        </div>
        <p class="flex items-center gap-2 text-xl font-semibold text-ink">
          {row.valueIcon ? <Pictogram name={row.valueIcon} size={32} class="text-primary-strong" /> : null}
          <bdi class="min-w-0 break-words">{row.value}</bdi>
        </p>
        {status ? (
          <p role="status" class={`flex items-center gap-1 text-sm ${status.tone}`}>
            <Pictogram name={status.icon} size={20} />
            {t(status.key)}
          </p>
        ) : null}
      </div>
    </li>
  );
}
