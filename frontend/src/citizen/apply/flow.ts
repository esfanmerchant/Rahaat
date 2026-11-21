import { effect, signal } from '@preact/signals';
import { actingScope } from '../../shared/acting';
import { onSessionEnd, session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure, type Result } from '../../shared/api/problem';
import type {
  ApplicationOut,
  DocumentKind,
  DocumentView,
  IncomeBand,
  SubmitOut,
} from '../../shared/api/types';
import { lang, messageKeyFor, type MessageKey } from '../../shared/i18n';
import { newId } from '../../shared/ids';
import { online } from '../../shared/network';
import {
  enqueueConsent,
  enqueueCreate,
  enqueuePatch,
  enqueueSubmit,
  enqueueUpload,
  hasQueued,
  ops,
  opResults,
  queuedFields,
  resolveApp,
  runOutbox,
  schedulePersist,
  sendingId,
  setDraftRestorer,
  setDraftSource,
  setTransport,
  storedIds,
  updateOp,
  type CreateOp,
  type FieldInput,
  type Op,
  type Outcome,
  type PatchOp,
  type SubmitOp,
  type UploadOp,
} from './outbox';

export { newId };

/**
 * The guided application (PLAN D1.3): one question per screen. Every answer
 * goes into the outbox (outbox.ts), which sends it at once when online and
 * keeps it sealed on the phone when not. The draft is in memory, and sealed in
 * the vault next to the queue so an offline reload can show it again; after an
 * online reload it is read back from the server with the queued answers on top.
 */
export type StepId = 'consent' | 'card' | 'name' | 'household' | 'income' | 'widow' | 'disability' | 'aid' | 'review';

export const STEPS: readonly StepId[] = [
  'consent',
  'card',
  'name',
  'household',
  'income',
  'widow',
  'disability',
  'aid',
  'review',
];

export function isStep(value: string | undefined): value is StepId {
  return STEPS.includes(value as StepId);
}

export function stepPath(step: StepId): string {
  return `/apply/${step}`;
}

/** true, false, or null for "I do not know" (sent as no value; unknown stays unknown). */
export type Tri = boolean | null;

export interface Answers {
  household_size?: number;
  income_band?: IncomeBand;
  is_widow?: Tri;
  has_disability?: Tri;
  receives_other_aid?: Tri;
}
export type AnswerField = keyof Answers;
export type SavedField = AnswerField | 'full_name';
/** waiting: in memory only; stored: sealed on this phone; sending; sent: the server has it; failed. */
export type SaveState = 'waiting' | 'stored' | 'sending' | 'sent' | 'failed';
/**
 * accepted: the photo is good. check: a person will check it. gave_up: three
 * tries failed. queued: saved on this phone, not checked yet.
 */
export type CardState = 'none' | 'accepted' | 'check' | 'gave_up' | 'queued';

export interface Draft {
  /** The user this draft belongs to; a sealed draft is only restored for its owner. */
  owner: string | null;
  applicationId: string | null;
  version: number;
  /** Client-generated id for creating the application: the same id creates once. */
  clientOpId: string;
  consentGiven: boolean;
  card: CardState;
  cardTries: number;
  /** The last retake hint, spoken again when the person comes back to the card. */
  cardHint: MessageKey | null;
  /** The name read from the card (OCR or signed QR), shown for confirmation. */
  cardName: string | null;
  /** Answer to "Is this your name?"; undefined while not asked. */
  nameAnswer: Tri | undefined;
  answers: Answers;
  /** Set by "Change" on the review screen: the next answer returns to the review. */
  returnToReview: boolean;
  submitKey: string | null;
}

export const draft = signal<Draft | null>(null);
/** A write was refused because consent is missing (409 consent_required). */
export const consentNeeded = signal(false);
/** The last save that failed for a reason other than the network. */
export const saveFailure = signal<ApiFailure | null>(null);
/** The application and decision returned by the last submit. */
export const lastSubmit = signal<SubmitOut | null>(null);
/** Per answer, this session: sent, or why it failed. */
export const fieldOutcomes = signal<Readonly<Partial<Record<SavedField, { state: 'sent' } | { state: 'failed'; why: MessageKey }>>>>({});

export const MAX_CARD_TRIES = 3;

function currentUser(): string | null {
  const now = session.peek();
  if (now.status !== 'signed-in') return null;
  // A helper's draft belongs to the family in front of them, not to the helper.
  const family = actingScope();
  return family ? `${now.user.id}:${family}` : now.user.id;
}

function freshDraft(): Draft {
  return {
    owner: currentUser(),
    applicationId: null,
    version: 1,
    clientOpId: newId(),
    consentGiven: false,
    card: 'none',
    cardTries: 0,
    cardHint: null,
    cardName: null,
    nameAnswer: undefined,
    answers: {},
    returnToReview: false,
    submitKey: null,
  };
}

function update(change: Partial<Draft>): void {
  const current = draft.peek();
  if (current) draft.value = { ...current, ...change };
}

function setOutcome(fields: readonly string[], outcome: { state: 'sent' } | { state: 'failed'; why: MessageKey } | null): void {
  if (fields.length === 0) return;
  const next = { ...fieldOutcomes.peek() };
  for (const field of fields) {
    if (outcome) next[field as SavedField] = outcome;
    else delete next[field as SavedField];
  }
  fieldOutcomes.value = next;
}

/** Forget the draft in memory (a consent change, sign-out). Queued answers stay in the outbox. */
export function resetFlow(): void {
  draft.value = null;
  consentNeeded.value = false;
  saveFailure.value = null;
  lastSubmit.value = null;
  fieldOutcomes.value = {};
  versions.clear();
}

onSessionEnd(resetFlow);

// The draft is sealed next to the queue; a sealed draft comes back only for its owner.
setDraftSource(() => draft.peek());
setDraftRestorer((saved) => {
  const candidate = saved as Draft | null;
  if (!candidate || typeof candidate !== 'object' || draft.peek()) return;
  if (candidate.owner !== currentUser()) return;
  draft.value = candidate;
});
effect(() => {
  void draft.value;
  schedulePersist();
});

function isConsentRequired(failure: ApiFailure): boolean {
  return failure.kind === 'conflict' && failure.problem?.code === 'consent_required';
}

function noteFailure(failure: ApiFailure): void {
  if (isConsentRequired(failure)) consentNeeded.value = true;
}

/** The version the server holds now, per application. */
const versions = new Map<string, number>();

function adopt(app: ApplicationOut): void {
  versions.set(app.id, app.version);
  const d = draft.peek();
  if (d && (d.applicationId === app.id || d.applicationId === null)) update({ applicationId: app.id, version: app.version });
}

const CARD_PROVENANCE = new Set(['ocr', 'qr_signed']);

/** The name the server read from the card, or null (no card yet, or not from the card). */
function nameFromCard(app: ApplicationOut): string | null {
  const field = app.form.full_name;
  if (!field || !CARD_PROVENANCE.has(field.provenance)) return null;
  const value = field.value?.trim();
  return value ? value : null;
}

// ---- field status ------------------------------------------------------------------------------

/** Where an answer is: in a queued op (waiting, stored, sending), or sent or failed this session. */
export function fieldState(field: SavedField): { state: SaveState; why?: MessageKey } | undefined {
  const queue = ops.value;
  const sending = sendingId.value;
  const stored = storedIds.value;
  for (let i = queue.length - 1; i >= 0; i -= 1) {
    const op = queue[i];
    if (op?.kind !== 'patch' || !(field in op.fields)) continue;
    if (sending === op.id) return { state: 'sending' };
    return { state: stored.has(op.id) ? 'stored' : 'waiting' };
  }
  const outcome = fieldOutcomes.value[field];
  if (!outcome) return undefined;
  return outcome.state === 'failed' ? { state: 'failed', why: outcome.why } : { state: 'sent' };
}

export function unsavedCount(): number {
  return Object.keys(queuedFields(draft.peek()?.applicationId ?? null)).length;
}

// ---- starting and resuming ---------------------------------------------------------------------

/** Rebuild the draft from an application the server already has, with the queued answers on top. */
function draftFrom(app: ApplicationOut): Draft {
  const form = app.form;
  const answers: Answers = {};
  // A null value cannot be told apart from "not asked yet", so it is asked again.
  if (typeof form.household_size?.value === 'number') answers.household_size = form.household_size.value;
  if (form.income_band?.value) answers.income_band = form.income_band.value;
  if (typeof form.is_widow?.value === 'boolean') answers.is_widow = form.is_widow.value;
  if (typeof form.has_disability?.value === 'boolean') answers.has_disability = form.has_disability.value;
  if (typeof form.receives_other_aid?.value === 'boolean') answers.receives_other_aid = form.receives_other_aid.value;
  // Answers given on this phone and not sent yet win: they are newer.
  const queued = queuedFields(app.id);
  for (const [field, input] of Object.entries(queued)) {
    if (field in ANSWER_FIELDS) (answers as Record<string, unknown>)[field] = input.value;
  }
  const card = (app.documents ?? []).filter((doc) => doc.kind === 'rahat_id').pop();
  const photoQueued = ops.peek().some((op) => op.kind === 'upload' && op.docKind === 'rahat_id' && (op.app === app.id || op.app === null));
  versions.set(app.id, app.version);
  return {
    ...freshDraft(),
    applicationId: app.id,
    version: app.version,
    consentGiven: true,
    card: photoQueued ? 'queued' : card ? (card.accepted ? (isPersonWillCheck(card) ? 'check' : 'accepted') : 'none') : 'none',
    cardName: nameFromCard(app),
    nameAnswer: 'full_name' in queued ? false : undefined,
    answers,
  };
}

const ANSWER_FIELDS: Readonly<Record<AnswerField, true>> = {
  household_size: true,
  income_band: true,
  is_widow: true,
  has_disability: true,
  receives_other_aid: true,
};

/**
 * Load the draft for /apply: the one in memory (or sealed on the phone), else
 * the person's unfinished application on the server, else a new draft that
 * starts with consent.
 */
export async function startOrResume(): Promise<Result<Draft>> {
  const current = draft.peek();
  if (current) return { ok: true, data: current };
  const list = await call(api.GET('/v1/applications'));
  if (!list.ok) return list;
  const open = list.data.items
    .filter((item) => item.status === 'draft')
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  if (draft.peek()) return { ok: true, data: draft.peek() as Draft }; // the vault opened meanwhile
  if (!open) {
    draft.value = freshDraft();
    return { ok: true, data: draft.value };
  }
  const app = await call(api.GET('/v1/applications/{application_id}', { params: { path: { application_id: open.id } } }));
  if (!app.ok) return app;
  draft.value = draftFrom(app.data);
  return { ok: true, data: draft.value };
}

/** Whether a step still needs an answer. */
export function stepDone(d: Draft, step: StepId): boolean {
  switch (step) {
    case 'consent':
      return d.consentGiven && (d.applicationId !== null || hasQueued('create'));
    case 'card':
      return d.card !== 'none';
    case 'name':
      return d.cardName === null || d.nameAnswer !== undefined;
    case 'household':
      return d.answers.household_size !== undefined;
    case 'income':
      return d.answers.income_band !== undefined;
    case 'widow':
      return d.answers.is_widow !== undefined;
    case 'disability':
      return d.answers.has_disability !== undefined;
    case 'aid':
      return d.answers.receives_other_aid !== undefined;
    case 'review':
      return false;
  }
}

/** The application exists on the server, or is about to (its create op waits in the outbox). */
export function hasApplication(d: Draft): boolean {
  return d.applicationId !== null || (d.consentGiven && hasQueued('create'));
}

export function firstOpenStep(d: Draft): StepId {
  return STEPS.find((step) => !stepDone(d, step)) ?? 'review';
}

/** The step after `step`; skips the name question when no name was read from the card. */
export function nextStep(d: Draft, step: StepId): StepId {
  if (d.returnToReview && step !== 'card') return 'review';
  let index = STEPS.indexOf(step) + 1;
  while (STEPS[index] === 'name' && d.cardName === null) index += 1;
  return STEPS[index] ?? 'review';
}

export function previousStep(d: Draft, step: StepId): StepId | null {
  let index = STEPS.indexOf(step) - 1;
  while (STEPS[index] === 'name' && d.cardName === null) index -= 1;
  if (STEPS[index] === 'consent' && d.consentGiven) return null; // consent is not asked twice
  return STEPS[index] ?? null;
}

// ---- waiting for one op ------------------------------------------------------------------------

/**
 * Run the queue and say what became of one op: done, failed, or still queued
 * (no network: it is kept and goes later).
 */
async function settle(op: Op): Promise<{ state: 'done'; result?: unknown } | { state: 'failed'; failure: ApiFailure } | { state: 'queued' }> {
  await runOutbox();
  const result = opResults.peek().get(op.id);
  if (result?.state === 'done') return { state: 'done', result: result.result };
  if (result?.state === 'failed') return { state: 'failed', failure: result.failure };
  return { state: 'queued' };
}

// ---- consent and creating the application -------------------------------------------------------

export const CONSENT_SCOPES = ['identity', 'contact', 'household', 'income', 'documents'] as const;

/**
 * Yes on the consent screen: record the consent, then create the application.
 * Offline both wait in the outbox and the person goes on answering; they are
 * sent first when the network returns.
 */
export async function giveConsent(): Promise<Result<{ queued: boolean }>> {
  const d = draft.peek();
  if (!d) return { ok: false, failure: { kind: 'server' } };
  const consentOp = !d.consentGiven || consentNeeded.peek() ? enqueueConsent() : null;
  const createOp = d.applicationId ? null : enqueueCreate(d.clientOpId, lang.peek());
  update({ consentGiven: true });
  consentNeeded.value = false;
  for (const op of [consentOp, createOp]) {
    if (!op) continue;
    const outcome = await settle(op);
    if (outcome.state === 'failed') {
      update({ consentGiven: false });
      return { ok: false, failure: outcome.failure };
    }
    if (outcome.state === 'queued') return { ok: true, data: { queued: true } };
  }
  return { ok: true, data: { queued: false } };
}

// ---- answers -----------------------------------------------------------------------------------

/** A tapped answer. The server decides what is verified, so `verified` is never sent. */
function tapped(value: unknown): FieldInput {
  return value === null ? { value: null, confidence: 0, provenance: 'tapped' } : { value, confidence: 1, provenance: 'tapped' };
}

/** Record an answer and send it (or keep it on the phone). null means "I do not know". */
export function answer<F extends AnswerField>(field: F, value: NonNullable<Answers[F]> | null): void {
  const d = draft.peek();
  if (!d) return;
  draft.value = { ...d, answers: { ...d.answers, [field]: value } };
  setOutcome([field], null);
  enqueuePatch(d.applicationId, { [field]: tapped(value) });
  void runOutbox();
}

/**
 * An answer the person said aloud and then confirmed with an icon. It goes
 * through the same outbox as a tapped one, with provenance `spoken` and the
 * confidence the server gave it.
 */
export function answerSpoken<F extends AnswerField>(field: F, value: NonNullable<Answers[F]> | null, confidence: number): void {
  const d = draft.peek();
  if (!d) return;
  draft.value = { ...d, answers: { ...d.answers, [field]: value } };
  setOutcome([field], null);
  enqueuePatch(d.applicationId, {
    [field]: value === null ? { value: null, confidence: 0, provenance: 'spoken' } : { value, confidence, provenance: 'spoken' },
  });
  void runOutbox();
}

/**
 * "Is this your name?" Yes keeps the name the server read from the card (no
 * write: a tapped value must not replace a signed one). No clears it, so the
 * name is unknown and a person checks it.
 */
export function answerName(isMine: Tri): void {
  const d = draft.peek();
  if (!d) return;
  draft.value = { ...d, nameAnswer: isMine };
  if (isMine === false) {
    setOutcome(['full_name'], null);
    enqueuePatch(d.applicationId, { full_name: tapped(null) });
    void runOutbox();
  }
}

/** Send what is waiting. Safe to call at any time. */
export function flush(): Promise<void> {
  return runOutbox();
}

// ---- documents ----------------------------------------------------------------------------------

/** The words for an upload result: the server's key when we know it, else one per quality. */
export function documentMessage(doc: DocumentView): MessageKey {
  if (doc.accepted) return messageKeyFor(doc.message_key) ?? 'doc_ok';
  return (
    messageKeyFor(doc.retake_hint) ??
    messageKeyFor(doc.message_key) ??
    messageKeyFor(`doc_retake_${doc.quality}`) ??
    'doc_retake_blurry'
  );
}

export function isPersonWillCheck(doc: DocumentView): boolean {
  return doc.accepted && documentMessage(doc) === 'doc_person_will_check';
}

/** A card photo's result, whenever it arrives (now, or later from the outbox). */
function applyCardResult(doc: DocumentView): void {
  const d = draft.peek();
  if (!d) return;
  if (doc.accepted) {
    update({ card: isPersonWillCheck(doc) ? 'check' : 'accepted', cardHint: null });
    return;
  }
  const tries = d.cardTries + 1;
  update(tries >= MAX_CARD_TRIES ? { card: 'gave_up', cardTries: tries, cardHint: null } : { card: 'none', cardTries: tries, cardHint: documentMessage(doc) });
}

/**
 * Add a photo (already resized on the device) to the outbox. Returns the op,
 * so a screen can wait for its result. A card photo's result updates the
 * draft by itself, also when it arrives after the person moved on.
 */
export function queuePhoto(photo: Blob, kind: DocumentKind, forApplication?: string): UploadOp {
  const d = draft.peek();
  const app = forApplication ?? d?.applicationId ?? lastSubmit.peek()?.application.id ?? null;
  const op = enqueueUpload(app, kind, photo);
  if (kind === 'rahat_id' && d && !forApplication) update({ card: 'queued' });
  void runOutbox();
  return op;
}

export function setCard(card: CardState, tries?: number): void {
  update(tries === undefined ? { card } : { card, cardTries: tries });
}

export function setReturnToReview(value: boolean): void {
  update({ returnToReview: value });
}

// ---- submitting ---------------------------------------------------------------------------------

/**
 * Send the application. The submit op goes after every queued answer, with one
 * Idempotency-Key for all tries, so it is never sent twice. Offline it waits
 * on the phone; `queued: true` says so.
 */
export async function submitApplication(): Promise<Result<SubmitOut | null>> {
  const d = draft.peek();
  if (!d || !hasApplication(d)) return { ok: false, failure: { kind: 'not_found', status: 404 } };
  const submitKey = d.submitKey ?? newId();
  update({ submitKey });
  const op = enqueueSubmit(d.applicationId, submitKey);
  const outcome = await settle(op);
  if (outcome.state === 'done') return { ok: true, data: outcome.result as SubmitOut };
  if (outcome.state === 'failed') return { ok: false, failure: outcome.failure };
  return { ok: true, data: null };
}

/** The card photo waiting in the outbox: sealed on the phone (true), in memory only (false), or none (null). */
export function cardPhotoStored(): boolean | null {
  const op = ops.value.find((item) => item.kind === 'upload' && item.docKind === 'rahat_id');
  return op ? storedIds.value.has(op.id) : null;
}

/** The submit op waiting in the outbox, if any. */
export function queuedSubmit(): SubmitOp | null {
  return ops.value.find((op): op is SubmitOp => op.kind === 'submit') ?? null;
}

// ---- the REST transport --------------------------------------------------------------------------

let programId: string | null = null;

function waitOrRetry(failure: ApiFailure): Outcome {
  if (failure.kind === 'offline') return { type: 'wait', why: 'offline' };
  if (failure.kind === 'unauthenticated') return { type: 'wait', why: 'session' };
  if (failure.kind === 'network' || failure.kind === 'server' || failure.kind === 'rate_limited') return { type: 'retry', failure };
  if (isConsentRequired(failure)) {
    consentNeeded.value = true;
    return { type: 'wait', why: 'consent' };
  }
  return { type: 'drop', failure };
}

async function getApplication(id: string): Promise<Result<ApplicationOut>> {
  return call(api.GET('/v1/applications/{application_id}', { params: { path: { application_id: id } } }));
}

async function sendConsent(op: Op & { kind: 'consent' }): Promise<Outcome> {
  const result = await call(
    api.POST('/v1/consents', {
      body: { purpose: 'relief_application', field_scopes: [...CONSENT_SCOPES], expires_in_days: 180 },
      headers: { 'Idempotency-Key': op.key },
    }),
  );
  if (result.ok) {
    consentNeeded.value = false;
    return { type: 'done' };
  }
  // A consent for this purpose is already active (perhaps narrowed): that is consent.
  if (result.failure.kind === 'conflict' && result.failure.problem?.code === 'consent_exists') return { type: 'done' };
  return waitOrRetry(result.failure);
}

async function sendCreate(op: CreateOp): Promise<Outcome> {
  const d = draft.peek();
  if (d?.applicationId && d.clientOpId === op.clientOpId) return { type: 'done' };
  if (!programId) {
    const programs = await call(api.GET('/v1/programs'));
    if (!programs.ok) return waitOrRetry(programs.failure);
    const program = programs.data.find((item) => item.active !== false) ?? programs.data[0];
    if (!program) return { type: 'drop', failure: { kind: 'not_found', status: 404 } };
    programId = program.id;
  }
  const created = await call(
    api.POST('/v1/applications', {
      body: { program_id: programId, client_op_id: op.clientOpId, form: { form_version: 'v1', language: op.lang } },
      headers: { 'Idempotency-Key': op.clientOpId },
    }),
  );
  if (created.ok) {
    adopt(created.data);
    resolveApp(created.data.id);
    return { type: 'done', result: created.data };
  }
  // One open application per program: carry on with the one the person already has.
  const problem = created.failure.problem as (ApiFailure['problem'] & { application_id?: string }) | undefined;
  if (created.failure.kind === 'conflict' && problem?.code === 'application_exists' && problem.application_id) {
    const existing = await getApplication(problem.application_id);
    if (!existing.ok) return waitOrRetry(existing.failure);
    if (existing.data.status !== 'draft' && existing.data.status !== 'needs_proof') {
      return { type: 'drop', failure: created.failure };
    }
    adopt(existing.data);
    resolveApp(existing.data.id);
    return { type: 'done', result: existing.data };
  }
  noteFailure(created.failure);
  return waitOrRetry(created.failure);
}

function sameValue(server: { value?: unknown; provenance?: string } | null | undefined, mine: FieldInput): boolean {
  if (!server) return false;
  return server.provenance === mine.provenance && JSON.stringify(server.value ?? null) === JSON.stringify(mine.value ?? null);
}

/** The answers that are not queued again after this op (their status becomes "sent"). */
function settledFields(op: PatchOp, fields: readonly string[]): string[] {
  const later = new Set<string>();
  for (const item of ops.peek()) if (item.kind === 'patch' && item.id !== op.id) for (const f of Object.keys(item.fields)) later.add(f);
  return fields.filter((field) => !later.has(field));
}

async function sendPatch(op: PatchOp): Promise<Outcome> {
  const app = op.app ?? draft.peek()?.applicationId ?? null;
  if (!app) return { type: 'wait', why: 'create' };
  const fields = Object.keys(op.fields);
  if (fields.length === 0) return { type: 'done' };
  const baseVersion = versions.get(app) ?? (draft.peek()?.applicationId === app ? draft.peek()?.version : undefined);
  if (baseVersion === undefined) {
    const latest = await getApplication(app);
    if (!latest.ok) return waitOrRetry(latest.failure);
    adopt(latest.data);
    return { type: 'again' };
  }
  const result = await call(
    api.PATCH('/v1/applications/{application_id}', {
      params: { path: { application_id: app } },
      body: { base_version: baseVersion, form_patch: op.fields },
    }),
  );
  if (result.ok) {
    adopt(result.data);
    saveFailure.value = null;
    setOutcome(settledFields(op, fields), { state: 'sent' });
    return { type: 'done', result: result.data };
  }
  const failure = result.failure;
  const code = failure.problem?.code;
  if (failure.kind === 'conflict' && code === 'version_conflict') {
    // The version moved on (another device, or our own answer whose response was lost).
    // These are the person's answers given just now: read the latest and send again,
    // without the answers the server already has, so nothing is written twice.
    const latest = await getApplication(app);
    if (!latest.ok) return waitOrRetry(latest.failure);
    adopt(latest.data);
    const form = latest.data.form as unknown as Record<string, { value?: unknown; provenance?: string } | null | undefined>;
    const remaining = Object.fromEntries(Object.entries(op.fields).filter(([field, input]) => !sameValue(form[field], input)));
    const arrived = fields.filter((field) => !(field in remaining));
    setOutcome(settledFields(op, arrived), { state: 'sent' });
    if (Object.keys(remaining).length === 0) return { type: 'done', result: latest.data };
    updateOp<PatchOp>(op.id, { fields: remaining });
    return { type: 'again' };
  }
  if (failure.kind === 'conflict' && code === 'consent_scope_missing') {
    // The person chose to share less: these answers cannot be written; a person checks them instead.
    const missing = new Set((failure.problem as { missing_scopes?: string[] } | undefined)?.missing_scopes ?? []);
    const refused = fields.filter((field) => missing.size === 0 || missing.has(SCOPE_OF[field] ?? ''));
    setOutcome(refused, { state: 'failed', why: 'mydata_scope_refused' });
    const remaining = Object.fromEntries(Object.entries(op.fields).filter(([field]) => !refused.includes(field)));
    if (Object.keys(remaining).length === 0) return { type: 'drop', failure };
    updateOp<PatchOp>(op.id, { fields: remaining });
    return { type: 'again' };
  }
  if (failure.kind === 'conflict' && code === 'not_editable') {
    setOutcome(fields, { state: 'failed', why: 'mydata_not_editable' });
    return { type: 'drop', failure };
  }
  const outcome = waitOrRetry(failure);
  if (outcome.type === 'drop') {
    saveFailure.value = failure;
    setOutcome(fields, { state: 'failed', why: 'apply_save_failed' });
  }
  return outcome;
}

/** Which consent scope a form field needs (backend applications/forms.py FIELD_SCOPE). */
const SCOPE_OF: Readonly<Record<string, string>> = {
  full_name: 'identity',
  national_id: 'identity',
  dob: 'identity',
  gender: 'identity',
  phone: 'contact',
  payout_account: 'contact',
  district: 'household',
  household_size: 'household',
  is_widow: 'household',
  has_disability: 'household',
  income_band: 'income',
  receives_other_aid: 'income',
};

async function sendUpload(op: UploadOp, blob: () => Promise<Blob | undefined>): Promise<Outcome> {
  const app = op.app ?? draft.peek()?.applicationId ?? null;
  if (!app) return { type: 'wait', why: 'create' };
  const photo = await blob();
  if (!photo) return { type: 'wait', why: 'vault' };
  if (op.docsBefore === undefined || op.ambiguous) {
    const latest = await getApplication(app);
    if (!latest.ok) return waitOrRetry(latest.failure);
    adopt(latest.data);
    const ofKind = (latest.data.documents ?? []).filter((doc) => doc.kind === op.docKind);
    if (op.ambiguous && op.docsBefore !== undefined && ofKind.length > op.docsBefore) {
      // The earlier try arrived although its answer was lost: use that result, do not send the photo again.
      const doc = ofKind[ofKind.length - 1] as DocumentView;
      return uploaded(op, app, doc, latest.data.version);
    }
    updateOp<UploadOp>(op.id, { docsBefore: ofKind.length, ambiguous: false });
  }
  // From here a lost answer is ambiguous: the next try first looks for the photo on the server.
  updateOp<UploadOp>(op.id, { ambiguous: true });
  const body = new FormData();
  body.append('file', photo, op.docKind === 'rahat_id' ? 'card.jpg' : 'proof.jpg');
  body.append('kind', op.docKind);
  const result = await call(
    api.POST('/v1/applications/{application_id}/documents', {
      params: { path: { application_id: app } },
      // openapi-fetch sends FormData as multipart; the generated type describes the fields.
      body: body as unknown as { file: string; kind: DocumentKind },
      headers: { 'Idempotency-Key': op.key },
    }),
  );
  if (result.ok) return uploaded(op, app, result.data.document, result.data.application_version);
  // The server answered, so it did not keep the photo: a new try is a clean one.
  if (result.failure.status !== undefined) updateOp<UploadOp>(op.id, { ambiguous: false });
  noteFailure(result.failure);
  return waitOrRetry(result.failure);
}

async function uploaded(op: UploadOp, app: string, doc: DocumentView, version: number): Promise<Outcome> {
  versions.set(app, Math.max(versions.get(app) ?? 0, version));
  const d = draft.peek();
  if (d?.applicationId === app) {
    update({ version: Math.max(d.version, version) });
    if (op.docKind === 'rahat_id') {
      applyCardResult(doc);
      if (doc.accepted) {
        const latest = await getApplication(app);
        if (latest.ok) {
          adopt(latest.data);
          update({ cardName: nameFromCard(latest.data), nameAnswer: undefined });
        }
      }
    }
  }
  return { type: 'done', result: doc };
}

async function sendSubmit(op: SubmitOp): Promise<Outcome> {
  const app = op.app ?? draft.peek()?.applicationId ?? null;
  if (!app) return { type: 'wait', why: 'create' };
  const result = await call(
    api.POST('/v1/applications/{application_id}/submit', {
      params: { path: { application_id: app } },
      headers: { 'Idempotency-Key': op.key },
    }),
  );
  if (result.ok) {
    lastSubmit.value = result.data;
    if (draft.peek()?.applicationId === app) draft.value = null; // the application is no longer a draft
    return { type: 'done', result: result.data };
  }
  noteFailure(result.failure);
  return waitOrRetry(result.failure);
}

setTransport({
  send(op, blob) {
    switch (op.kind) {
      case 'consent':
        return sendConsent(op);
      case 'create':
        return sendCreate(op);
      case 'patch':
        return sendPatch(op);
      case 'upload':
        return sendUpload(op, blob);
      case 'submit':
        return sendSubmit(op);
      case 'appeal':
      case 'complaint':
        // Appeals and complaints are written in a lazy chunk, loaded only when one is sent.
        return import('../report/send').then((m) => m.sendReport(op)).catch(() => ({ type: 'wait', why: 'offline' }) as const);
    }
  },
});

// A consent given again releases the answers that waited for it.
consentNeeded.subscribe((needed) => {
  if (!needed && online.peek()) void runOutbox();
});
