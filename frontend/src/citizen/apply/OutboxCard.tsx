import { Pictogram, type PictogramName } from '../../shared/components/Pictogram';
import { Spinner } from '../../shared/components/Spinner';
import { t, type MessageKey } from '../../shared/i18n';
import { opPhase, ops, sentLog, type Op, type OpKind } from './outbox';

/** What each answer is called on the review screen, reused for the outbox list. */
const FIELD_LABEL: Readonly<Record<string, MessageKey>> = {
  full_name: 'review_name',
  household_size: 'review_household',
  income_band: 'review_income',
  is_widow: 'review_widow',
  has_disability: 'review_disability',
  receives_other_aid: 'review_aid',
};

const KIND_LABEL: Record<Exclude<OpKind, 'patch'>, MessageKey> = {
  consent: 'outbox_start',
  create: 'outbox_start',
  upload: 'outbox_photo',
  submit: 'outbox_submit',
  appeal: 'outbox_appeal',
  complaint: 'outbox_complaint',
};

function labels(kind: OpKind, fields: readonly string[]): MessageKey[] {
  if (kind !== 'patch') return [KIND_LABEL[kind]];
  return fields.map((field) => FIELD_LABEL[field]).filter((key): key is MessageKey => key !== undefined);
}

const PHASE: Record<'sending' | 'stored' | 'waiting' | 'sent', { icon: PictogramName | null; key: MessageKey; tone: string }> = {
  stored: { icon: 'phone-saved', key: 'outbox_title', tone: 'text-warning-ink' },
  waiting: { icon: 'clock', key: 'apply_waiting', tone: 'text-warning-ink' },
  sending: { icon: null, key: 'outbox_sending', tone: 'text-ink-muted' },
  sent: { icon: 'yes', key: 'outbox_sent', tone: 'text-primary-strong' },
};

function Row({ label, phase }: { label: MessageKey; phase: keyof typeof PHASE }) {
  const spec = PHASE[phase];
  return (
    <li class={`flex min-h-tap items-center gap-3 border-b border-line py-1 last:border-b-0 ${spec.tone}`}>
      {spec.icon ? <Pictogram name={spec.icon} size={28} /> : <Spinner size={24} />}
      <span class="flex-1 text-base font-semibold text-ink">{t(label)}</span>
      <span class="text-sm font-semibold">{t(spec.key)}</span>
    </li>
  );
}

/**
 * Per-item status of the outbox (D1.5): each answer, photo or send that is
 * saved on this phone, being sent, or sent a moment ago. Hidden when empty.
 */
export function OutboxCard() {
  const queue = ops.value;
  const sent = sentLog.value;
  if (queue.length === 0 && sent.length === 0) return null;
  const rows: Array<{ id: string; label: MessageKey; phase: keyof typeof PHASE }> = [];
  for (const op of queue as readonly Op[]) {
    const phase = opPhase(op);
    for (const label of labels(op.kind, op.kind === 'patch' ? Object.keys(op.fields) : [])) rows.push({ id: `${op.id}:${label}`, label, phase });
  }
  for (const item of sent) for (const label of labels(item.kind, item.fields)) rows.push({ id: `${item.id}:${label}`, label, phase: 'sent' });
  // One row per label: the newest state wins (a pending answer hides an older "sent" for it).
  const seen = new Set<string>();
  const unique = rows.filter((row) => (seen.has(row.label) ? false : (seen.add(row.label), true)));
  return (
    <section aria-labelledby="home-outbox" class="flex flex-col gap-2 rounded-lg border-2 border-line-strong bg-surface p-3">
      <h2 id="home-outbox" class="flex items-center gap-2 text-lg font-bold">
        <Pictogram name={queue.length > 0 ? 'phone-saved' : 'yes'} size={32} class="text-primary" />
        {t(queue.length > 0 ? 'outbox_title' : 'outbox_sent')}
      </h2>
      {queue.length > 0 ? <p class="text-base text-ink-muted">{t('outbox_home')}</p> : null}
      <ul class="flex flex-col" aria-live="polite">
        {unique.map((row) => (
          <Row key={row.id} label={row.label} phase={row.phase} />
        ))}
      </ul>
    </section>
  );
}
