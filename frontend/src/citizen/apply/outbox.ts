import { computed, signal } from '@preact/signals';
import { onSessionEnd } from '../../shared/api/auth';
import type { ApiFailure } from '../../shared/api/problem';
import type { DocumentKind } from '../../shared/api/types';
import type { Lang } from '../../shared/i18n';
import { beforeLock } from '../../shared/idle';
import { newId } from '../../shared/ids';
import { online } from '../../shared/network';
import { deleteItem, getBlob, getItem, onVaultOpen, putBlob, putItem, vaultState } from '../../shared/vault';

/**
 * The outbox (PLAN D1.5, 6.9): every write of the application goes through
 * this queue, in order, one at a time. Online it empties within a moment;
 * without a connection the operations wait, sealed in the phone's vault when
 * it is open, and go when the network returns. Nothing is lost on a reload
 * (the PIN opens the vault again) and nothing is sent twice:
 *
 * - consent and create carry an Idempotency-Key and a client_op_id;
 * - a patch carries base_version; a version conflict re-reads the
 *   application and re-applies the person's own answers, dropping those the
 *   server already has (a lost response is not a second write);
 * - submit carries one Idempotency-Key for every try;
 * - an upload counts the documents first, so after a lost response the photo
 *   that already arrived is found instead of being sent again.
 *
 * The queue talks to the server through a Transport. Today that is the REST
 * API (flow.ts); the batched POST /v1/sync can replace it without changing
 * the queue, because an op already has the sync shape: op_id, kind,
 * entity, base version, patch, created_at.
 */

/** A form value as the client may send it: tapped, never verified. */
export interface FieldInput {
  value: unknown;
  confidence: number;
  provenance: 'tapped';
}

interface OpBase {
  id: string;
  createdAt: string;
  tries: number;
  /** The application this op writes to; null until the create op has run. */
  app: string | null;
}
export interface ConsentOp extends OpBase {
  kind: 'consent';
  key: string;
}
export interface CreateOp extends OpBase {
  kind: 'create';
  clientOpId: string;
  lang: Lang;
}
export interface PatchOp extends OpBase {
  kind: 'patch';
  fields: Record<string, FieldInput>;
}
export interface UploadOp extends OpBase {
  kind: 'upload';
  docKind: DocumentKind;
  key: string;
  blobType: string;
  /** Documents of this kind on the application before the first try (finds a photo that arrived although its answer was lost). */
  docsBefore?: number;
  /** A try was sent and its answer never came. */
  ambiguous?: boolean;
}
export interface SubmitOp extends OpBase {
  kind: 'submit';
  key: string;
}
export type Op = ConsentOp | CreateOp | PatchOp | UploadOp | SubmitOp;
export type OpKind = Op['kind'];

export type Outcome =
  /** Applied (or already there): the op leaves the queue. */
  | { type: 'done'; result?: unknown }
  /** The state moved on (a version conflict was rebased): send the same op again now. */
  | { type: 'again' }
  /** Cannot go yet: no network, no session, no consent, vault locked, or the application is not created yet. */
  | { type: 'wait'; why: 'offline' | 'session' | 'consent' | 'vault' | 'create' }
  /** Failed for now (server error, timeout): try again later. */
  | { type: 'retry'; failure: ApiFailure }
  /** Refused for good: the op leaves the queue and its fields are marked failed. */
  | { type: 'drop'; failure: ApiFailure };

export interface Transport {
  send(op: Op, blob: () => Promise<Blob | undefined>): Promise<Outcome>;
}

/** What a waiting screen sees about one op. */
export type OpResult = { state: 'done'; result?: unknown } | { state: 'failed'; failure: ApiFailure };

export const ops = signal<readonly Op[]>([]);
/** The op being sent now. */
export const sendingId = signal<string | null>(null);
/** Ops sealed in the vault (the rest are in memory only). */
export const storedIds = signal<ReadonlySet<string>>(new Set());
/** Results of ops that left the queue in this session. */
export const opResults = signal<ReadonlyMap<string, OpResult>>(new Map());
/** Recently sent items, for the "sent" status on the home screen (memory only). */
export const sentLog = signal<ReadonlyArray<{ id: string; kind: OpKind; fields: string[] }>>([]);

export const pendingCount = computed(() => ops.value.length);

const blobs = new Map<string, Blob>();
let transport: Transport | null = null;

export function setTransport(next: Transport): void {
  transport = next;
}

export function opPhase(op: Op): 'sending' | 'stored' | 'waiting' {
  if (sendingId.value === op.id) return 'sending';
  return storedIds.value.has(op.id) ? 'stored' : 'waiting';
}

function base(app: string | null): OpBase {
  return { id: newId(), createdAt: new Date().toISOString(), tries: 0, app };
}

function setResult(id: string, result: OpResult): void {
  const next = new Map(opResults.peek());
  next.set(id, result);
  opResults.value = next;
}

// ---- adding ------------------------------------------------------------------------------------

/** Consent and create go first: everything else needs them. */
function enqueue(op: Op, front = false): Op {
  const list = ops.peek();
  if (front) {
    const firstOther = list.findIndex((item) => item.kind !== 'consent' && item.kind !== 'create');
    const at = firstOther === -1 ? list.length : firstOther;
    ops.value = [...list.slice(0, at), op, ...list.slice(at)];
  } else {
    ops.value = [...list, op];
  }
  schedulePersist();
  return op;
}

export function enqueueConsent(): ConsentOp {
  const existing = ops.peek().find((op): op is ConsentOp => op.kind === 'consent');
  return existing ?? (enqueue({ ...base(null), kind: 'consent', key: newId() }, true) as ConsentOp);
}

export function enqueueCreate(clientOpId: string, lang: Lang): CreateOp {
  const existing = ops.peek().find((op): op is CreateOp => op.kind === 'create' && op.clientOpId === clientOpId);
  return existing ?? (enqueue({ ...base(null), kind: 'create', clientOpId, lang }, true) as CreateOp);
}

/**
 * An answer. Merged into the last patch when that one is still waiting at the
 * end of the queue, so offline answers go as one write; a newer answer to the
 * same question replaces the older one.
 */
export function enqueuePatch(app: string | null, fields: Record<string, FieldInput>): void {
  const list = ops.peek();
  const last = list[list.length - 1];
  if (last && last.kind === 'patch' && last.app === app && sendingId.peek() !== last.id) {
    const merged: PatchOp = { ...last, fields: { ...last.fields, ...fields } };
    ops.value = [...list.slice(0, -1), merged];
    // The merged op must be sealed again before it counts as stored.
    const stored = new Set(storedIds.peek());
    stored.delete(last.id);
    storedIds.value = stored;
    schedulePersist();
    return;
  }
  enqueue({ ...base(app), kind: 'patch', fields });
}

export function enqueueUpload(app: string | null, docKind: DocumentKind, photo: Blob): UploadOp {
  const op: UploadOp = { ...base(app), kind: 'upload', docKind, key: newId(), blobType: photo.type || 'image/jpeg' };
  blobs.set(op.id, photo);
  return enqueue(op) as UploadOp;
}

export function enqueueSubmit(app: string | null, key: string): SubmitOp {
  const existing = ops.peek().find((op): op is SubmitOp => op.kind === 'submit' && op.app === app);
  return existing ?? (enqueue({ ...base(app), kind: 'submit', key }) as SubmitOp);
}

/** Point waiting ops at the application once the create op has made it. */
export function resolveApp(app: string): void {
  ops.value = ops.peek().map((op) => (op.app === null && op.kind !== 'consent' && op.kind !== 'create' ? { ...op, app } : op));
  schedulePersist();
}

/** Queued answers for one application, newest last (so a rebuilt draft shows what the person gave). */
export function queuedFields(app: string | null): Record<string, FieldInput> {
  const out: Record<string, FieldInput> = {};
  for (const op of ops.peek()) {
    if (op.kind === 'patch' && (op.app === app || op.app === null)) Object.assign(out, op.fields);
  }
  return out;
}

export function hasQueued(kind: OpKind): boolean {
  return ops.peek().some((op) => op.kind === kind);
}

// ---- sending -----------------------------------------------------------------------------------

let running: Promise<void> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let failures = 0;

/** Send what is queued. Safe to call at any time; resolves when the queue is empty or must wait. */
export function runOutbox(): Promise<void> {
  running ??= loop().finally(() => {
    running = null;
  });
  return running;
}

function retryLater(): void {
  failures += 1;
  const delay = Math.min(30_000, 2_000 * 2 ** Math.min(failures - 1, 4));
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void runOutbox();
  }, delay);
}

function remove(id: string): void {
  ops.value = ops.peek().filter((op) => op.id !== id);
  blobs.delete(id);
  sealedBlobs.delete(id);
  void deleteItem(`blob:${id}`);
  schedulePersist();
}

async function blobFor(op: Op): Promise<Blob | undefined> {
  if (op.kind !== 'upload') return undefined;
  return blobs.get(op.id) ?? (await getBlob(`blob:${op.id}`, op.blobType));
}

async function loop(): Promise<void> {
  let again = 0;
  for (;;) {
    const op = ops.peek()[0];
    if (!op || !transport) return;
    if (!online.peek()) return;
    sendingId.value = op.id;
    let outcome: Outcome;
    try {
      outcome = await transport.send(op, () => blobFor(op));
    } catch {
      outcome = { type: 'retry', failure: { kind: 'server' } };
    }
    sendingId.value = null;
    const still = ops.peek().find((item) => item.id === op.id);
    if (!still) continue; // removed meanwhile (session ended, draft reset)
    switch (outcome.type) {
      case 'done':
        failures = 0;
        again = 0;
        remove(op.id);
        setResult(op.id, { state: 'done', result: outcome.result });
        sentLog.value = [
          { id: op.id, kind: op.kind, fields: op.kind === 'patch' ? Object.keys(op.fields) : [] },
          ...sentLog.peek(),
        ].slice(0, 8);
        continue;
      case 'again':
        again += 1;
        if (again > 3) {
          retryLater();
          return;
        }
        continue;
      case 'wait':
        return;
      case 'retry':
        ops.value = ops.peek().map((item) => (item.id === op.id ? { ...item, tries: item.tries + 1 } : item));
        retryLater();
        return;
      case 'drop':
        again = 0;
        remove(op.id);
        setResult(op.id, { state: 'failed', failure: outcome.failure });
        continue;
    }
  }
}

/** Update fields of a queued op (an upload's document count) and seal it again. */
export function updateOp<T extends Op>(id: string, change: Partial<T>): void {
  ops.value = ops.peek().map((op) => (op.id === id ? ({ ...op, ...change } as Op) : op));
  schedulePersist();
}

// ---- sealing in the vault ----------------------------------------------------------------------

interface Saved {
  v: 1;
  ops: Op[];
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;
let draftSource: (() => unknown) | null = null;

/** flow.ts gives the draft to seal next to the queue, so an offline reload can show it again. */
export function setDraftSource(source: () => unknown): void {
  draftSource = source;
}

export function schedulePersist(): void {
  if (persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void persistNow();
  }, 30);
}

let restoring = false;

/** Seal the queue, the photos and the draft. A no-op while the vault is locked (they stay in memory). */
export async function persistNow(): Promise<void> {
  if (vaultState.peek() !== 'open' || restoring) return;
  const snapshot = ops.peek();
  for (const op of snapshot) {
    const photo = blobs.get(op.id);
    if (op.kind === 'upload' && photo && !sealedBlobs.has(op.id) && (await putBlob(`blob:${op.id}`, photo))) sealedBlobs.add(op.id);
  }
  const saved = await putItem('outbox', { v: 1, ops: [...snapshot] } satisfies Saved);
  const draft = draftSource?.() ?? null;
  if (draft) await putItem('draft', draft);
  else await deleteItem('draft');
  // Changed while sealing: seal again, so the stored copy is never older than what the screen says.
  if (saved && ops.peek() === snapshot) storedIds.value = new Set(snapshot.map((op) => op.id));
  else if (saved) schedulePersist();
}

/** Photos already sealed (a photo never changes, so it is written once). */
const sealedBlobs = new Set<string>();

let restoreDraft: ((saved: unknown) => void) | null = null;

/** flow.ts decides whether a sealed draft replaces the one in memory. */
export function setDraftRestorer(restorer: (saved: unknown) => void): void {
  restoreDraft = restorer;
}

// The vault opened (sign-in or unlock): bring back what was sealed, then send it.
onVaultOpen(() => {
  restoring = true;
  void (async () => {
    try {
      const saved = await getItem<Saved>('outbox');
      const sealedDraft = await getItem<unknown>('draft');
      const inMemory = new Set(ops.peek().map((op) => op.id));
      const fromVault = (saved?.ops ?? []).filter((op) => !inMemory.has(op.id));
      if (fromVault.length > 0) ops.value = [...fromVault, ...ops.peek()];
      for (const op of fromVault) if (op.kind === 'upload') sealedBlobs.add(op.id);
      if (sealedDraft !== undefined) restoreDraft?.(sealedDraft);
      storedIds.value = new Set(fromVault.map((op) => op.id));
    } finally {
      restoring = false;
    }
    await persistNow();
    void runOutbox();
  })();
});

online.subscribe((isOnline) => {
  if (isOnline) {
    failures = 0;
    void runOutbox();
  }
});

/** Forget the queue in memory: the session ended or the phone locked. What was sealed stays sealed. */
export function forgetOutbox(): void {
  ops.value = [];
  blobs.clear();
  sealedBlobs.clear();
  sendingId.value = null;
  storedIds.value = new Set();
  opResults.value = new Map();
  sentLog.value = [];
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = null;
}

onSessionEnd(forgetOutbox);
// Before an idle lock wipes memory, seal what is not sealed yet.
beforeLock(() => persistNow());
