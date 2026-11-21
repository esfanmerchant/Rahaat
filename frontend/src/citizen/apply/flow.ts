import { signal } from '@preact/signals';
import { onSessionEnd } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure, type Result } from '../../shared/api/problem';
import type {
  ApplicationOut,
  DocumentKind,
  DocumentView,
  IncomeBand,
  SubmitOut,
} from '../../shared/api/types';
import { lang } from '../../shared/i18n';
import { online } from '../../shared/network';

/**
 * The guided application (PLAN D1.3): one question per screen. Each answer is
 * saved to the server as soon as it is given (PATCH with base_version). The
 * draft lives in memory only: no personal data in browser storage
 * (docs/DESIGN.md). After a reload the draft is read back from the server.
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
export type SaveState = 'saving' | 'saved' | 'waiting' | 'failed';
/** accepted: the photo is good. check: a person will check it. gave_up: three tries failed. */
export type CardState = 'none' | 'accepted' | 'check' | 'gave_up';

export interface Draft {
  applicationId: string | null;
  version: number;
  /** Client-generated id for creating the application: the same id creates once. */
  clientOpId: string;
  consentGiven: boolean;
  card: CardState;
  cardTries: number;
  /** The name read from the card (OCR or signed QR), shown for confirmation. */
  cardName: string | null;
  /** Answer to "Is this your name?"; undefined while not asked. */
  nameAnswer: Tri | undefined;
  answers: Answers;
  saves: Partial<Record<SavedField, SaveState>>;
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

export function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function freshDraft(): Draft {
  return {
    applicationId: null,
    version: 1,
    clientOpId: newId(),
    consentGiven: false,
    card: 'none',
    cardTries: 0,
    cardName: null,
    nameAnswer: undefined,
    answers: {},
    saves: {},
    returnToReview: false,
    submitKey: null,
  };
}

function update(change: Partial<Draft>): void {
  const current = draft.peek();
  if (current) draft.value = { ...current, ...change };
}

let pending: Record<string, unknown> = {};

/** Forget everything in memory: on sign-out, expiry, or another person signing in. */
export function resetFlow(): void {
  draft.value = null;
  pending = {};
  consentNeeded.value = false;
  saveFailure.value = null;
  lastSubmit.value = null;
}

onSessionEnd(resetFlow);

function isConsentRequired(failure: ApiFailure): boolean {
  return failure.kind === 'conflict' && failure.problem?.code === 'consent_required';
}

function noteFailure(failure: ApiFailure): void {
  if (isConsentRequired(failure)) consentNeeded.value = true;
}

function adopt(app: ApplicationOut): void {
  update({ applicationId: app.id, version: app.version });
}

const CARD_PROVENANCE = new Set(['ocr', 'qr_signed']);

/** The name the server read from the card, or null (no card yet, or not from the card). */
function nameFromCard(app: ApplicationOut): string | null {
  const field = app.form.full_name;
  if (!field || !CARD_PROVENANCE.has(field.provenance)) return null;
  const value = field.value?.trim();
  return value ? value : null;
}

// ---- starting and resuming ---------------------------------------------------------------------

/** Rebuild the draft from an application the server already has (resume after a reload). */
function draftFrom(app: ApplicationOut): Draft {
  const form = app.form;
  const answers: Answers = {};
  // A null value cannot be told apart from "not asked yet", so it is asked again.
  if (typeof form.household_size?.value === 'number') answers.household_size = form.household_size.value;
  if (form.income_band?.value) answers.income_band = form.income_band.value;
  if (typeof form.is_widow?.value === 'boolean') answers.is_widow = form.is_widow.value;
  if (typeof form.has_disability?.value === 'boolean') answers.has_disability = form.has_disability.value;
  if (typeof form.receives_other_aid?.value === 'boolean') answers.receives_other_aid = form.receives_other_aid.value;
  const saves: Draft['saves'] = {};
  for (const key of Object.keys(answers) as AnswerField[]) saves[key] = 'saved';
  const card = (app.documents ?? []).find((doc) => doc.kind === 'rahat_id');
  return {
    ...freshDraft(),
    applicationId: app.id,
    version: app.version,
    consentGiven: true,
    card: card ? (card.accepted ? 'accepted' : 'check') : 'none',
    cardName: nameFromCard(app),
    answers,
    saves,
  };
}

/**
 * Load the draft for /apply: the person's unfinished application if there is
 * one, otherwise a new draft that starts with consent.
 */
export async function startOrResume(): Promise<Result<Draft>> {
  const current = draft.peek();
  if (current) return { ok: true, data: current };
  const list = await call(api.GET('/v1/applications'));
  if (!list.ok) return list;
  const open = list.data.items
    .filter((item) => item.status === 'draft')
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
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
      return d.consentGiven && d.applicationId !== null;
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

// ---- consent and creating the application -------------------------------------------------------

let consentKey: string | null = null;
let programId: string | null = null;

/** Yes on the consent screen: record the consent, then create the application. */
export async function giveConsent(): Promise<Result<void>> {
  const d = draft.peek();
  if (!d) return { ok: false, failure: { kind: 'server' } };
  if (!d.consentGiven || consentNeeded.peek()) {
    consentKey ??= newId();
    const result = await call(
      api.POST('/v1/consents', {
        body: {
          purpose: 'relief_application',
          field_scopes: ['identity', 'contact', 'household', 'income', 'documents'],
          expires_in_days: 180,
        },
        headers: { 'Idempotency-Key': consentKey },
      }),
    );
    if (!result.ok) return result;
    consentKey = null;
    update({ consentGiven: true });
    consentNeeded.value = false;
  }
  const created = await ensureApplication();
  if (created.ok) void flush(); // answers held back by a missing consent go now
  return created;
}

async function ensureApplication(): Promise<Result<void>> {
  const d = draft.peek();
  if (!d) return { ok: false, failure: { kind: 'server' } };
  if (d.applicationId) return { ok: true, data: undefined };
  if (!programId) {
    const programs = await call(api.GET('/v1/programs'));
    if (!programs.ok) return programs;
    const program = programs.data.find((item) => item.active !== false) ?? programs.data[0];
    if (!program) return { ok: false, failure: { kind: 'not_found', status: 404 } };
    programId = program.id;
  }
  const created = await call(
    api.POST('/v1/applications', {
      body: {
        program_id: programId,
        client_op_id: d.clientOpId,
        form: { form_version: 'v1', language: lang.peek() },
      },
      headers: { 'Idempotency-Key': d.clientOpId },
    }),
  );
  if (!created.ok) {
    noteFailure(created.failure);
    return created;
  }
  adopt(created.data);
  return { ok: true, data: undefined };
}

// ---- saving answers ------------------------------------------------------------------------------

function setSaves(fields: readonly string[], state: SaveState): void {
  const d = draft.peek();
  if (!d || fields.length === 0) return;
  const saves = { ...d.saves };
  for (const field of fields) saves[field as SavedField] = state;
  draft.value = { ...d, saves };
}

/** A tapped answer. The server decides what is verified, so `verified` is never sent. */
function tapped(value: unknown): { value: unknown; confidence: number; provenance: 'tapped' } {
  return value === null ? { value: null, confidence: 0, provenance: 'tapped' } : { value, confidence: 1, provenance: 'tapped' };
}

/** Record an answer and save it. null means "I do not know". */
export function answer<F extends AnswerField>(field: F, value: NonNullable<Answers[F]> | null): void {
  const d = draft.peek();
  if (!d) return;
  draft.value = { ...d, answers: { ...d.answers, [field]: value } };
  pending[field] = tapped(value);
  setSaves([field], 'saving');
  void flush();
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
    pending.full_name = tapped(null);
    setSaves(['full_name'], 'saving');
    void flush();
  }
}

let flushing: Promise<void> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

/** Send the answers that are not saved yet. Safe to call at any time. */
export function flush(): Promise<void> {
  flushing ??= runFlush().finally(() => {
    flushing = null;
  });
  return flushing;
}

export function unsavedCount(): number {
  return Object.keys(pending).length;
}

async function runFlush(): Promise<void> {
  let conflicts = 0;
  for (;;) {
    const d = draft.peek();
    const fields = Object.keys(pending);
    if (!d?.applicationId || fields.length === 0) return;
    if (!online.peek()) {
      setSaves(fields, 'waiting');
      return;
    }
    const patch = pending;
    pending = {};
    setSaves(fields, 'saving');
    const result = await call(
      api.PATCH('/v1/applications/{application_id}', {
        params: { path: { application_id: d.applicationId } },
        body: { base_version: d.version, form_patch: patch },
      }),
    );
    if (draft.peek() !== null && draft.peek()?.applicationId !== d.applicationId) return; // person changed
    if (result.ok) {
      adopt(result.data);
      saveFailure.value = null;
      setSaves(
        fields.filter((field) => !(field in pending)),
        'saved',
      );
      continue;
    }
    pending = { ...patch, ...pending }; // keep any newer answer given meanwhile
    const failure = result.failure;
    if (failure.kind === 'conflict' && failure.problem?.code === 'version_conflict' && conflicts < 2) {
      // Someone (or our own lost response) moved the version on. These are the
      // person's answers given just now, so rebase onto the latest and resend.
      conflicts += 1;
      const latest = await call(
        api.GET('/v1/applications/{application_id}', { params: { path: { application_id: d.applicationId } } }),
      );
      if (latest.ok) {
        adopt(latest.data);
        continue;
      }
    }
    if (isConsentRequired(failure)) {
      consentNeeded.value = true;
      setSaves(fields, 'waiting');
      return;
    }
    if (failure.kind === 'offline' || failure.kind === 'network' || failure.kind === 'server') {
      setSaves(fields, 'waiting');
      if (failure.kind !== 'offline') {
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = setTimeout(() => void flush(), 8000);
      }
      return;
    }
    saveFailure.value = failure;
    setSaves(fields, 'failed');
    return;
  }
}

online.subscribe((isOnline) => {
  if (isOnline) void flush();
});

function waitForOnline(): Promise<void> {
  if (online.peek()) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const stop = online.subscribe((isOnline) => {
      if (!isOnline) return;
      queueMicrotask(() => stop());
      resolve();
    });
  });
}

// ---- documents ----------------------------------------------------------------------------------

/** Upload a photo (already resized on the device). On a card, reads back the name the server found. */
export async function uploadPhoto(
  photo: Blob,
  kind: DocumentKind,
  key: string,
  forApplication?: string,
): Promise<Result<DocumentView>> {
  const d = draft.peek();
  const applicationId = forApplication ?? d?.applicationId ?? lastSubmit.peek()?.application.id ?? null;
  if (!applicationId) return { ok: false, failure: { kind: 'not_found', status: 404 } };
  const body = new FormData();
  body.append('file', photo, kind === 'rahat_id' ? 'card.jpg' : 'proof.jpg');
  body.append('kind', kind);
  const result = await call(
    api.POST('/v1/applications/{application_id}/documents', {
      params: { path: { application_id: applicationId } },
      // openapi-fetch sends FormData as multipart; the generated type describes the fields.
      body: body as unknown as { file: string; kind: DocumentKind },
      headers: { 'Idempotency-Key': key },
    }),
  );
  if (!result.ok) {
    noteFailure(result.failure);
    return result;
  }
  if (d?.applicationId === applicationId) {
    update({ version: Math.max(d.version, result.data.application_version) });
    if (kind === 'rahat_id' && result.data.document.accepted) {
      const app = await call(
        api.GET('/v1/applications/{application_id}', { params: { path: { application_id: applicationId } } }),
      );
      if (app.ok) update({ version: app.data.version, cardName: nameFromCard(app.data), nameAnswer: undefined });
    }
  }
  return { ok: true, data: result.data.document };
}

export function setCard(card: CardState, tries?: number): void {
  update(tries === undefined ? { card } : { card, cardTries: tries });
}

export function setReturnToReview(value: boolean): void {
  update({ returnToReview: value });
}

// ---- submitting ---------------------------------------------------------------------------------

export const submitWaiting = signal(false);

/**
 * Send the application. Waits for unsaved answers and for the network, so a
 * tap while offline is not lost; the same Idempotency-Key is used for every
 * try, so a retry never submits twice.
 */
export async function submitApplication(): Promise<Result<SubmitOut>> {
  const d = draft.peek();
  if (!d?.applicationId) return { ok: false, failure: { kind: 'not_found', status: 404 } };
  const submitKey = d.submitKey ?? newId();
  update({ submitKey });
  for (let attempt = 0; ; attempt += 1) {
    if (!online.peek()) {
      submitWaiting.value = true;
      await waitForOnline();
    }
    await flush();
    if (unsavedCount() === 0) break;
    if (consentNeeded.peek() || saveFailure.peek() || attempt >= 4) break;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  submitWaiting.value = false;
  if (consentNeeded.peek()) return { ok: false, failure: { kind: 'conflict', status: 409 } };
  const failed = saveFailure.peek();
  if (failed) return { ok: false, failure: failed };
  if (unsavedCount() > 0) return { ok: false, failure: { kind: online.peek() ? 'network' : 'offline' } };
  const current = draft.peek();
  if (!current?.applicationId) return { ok: false, failure: { kind: 'not_found', status: 404 } };
  const result = await call(
    api.POST('/v1/applications/{application_id}/submit', {
      params: { path: { application_id: current.applicationId } },
      headers: { 'Idempotency-Key': submitKey },
    }),
  );
  if (!result.ok) {
    noteFailure(result.failure);
    return result;
  }
  lastSubmit.value = result.data;
  draft.value = null; // the application is no longer a draft
  pending = {};
  return result;
}
