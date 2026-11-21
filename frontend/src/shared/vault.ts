import { signal } from '@preact/signals';
import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { AuthOut } from './api/types';

/**
 * Encrypted storage on this phone for work that is not sent yet (the outbox
 * and the unfinished draft). Nothing else of a person is ever written to
 * browser storage, and tokens never are.
 *
 * - The key is AES-GCM 256, derived from the PIN with PBKDF2-SHA-256 and a
 *   random salt stored next to the data. It is created at sign-in, is not
 *   extractable, and lives in memory only. A reload, an idle lock or a
 *   sign-out drops it; the PIN opens the data again.
 * - Every record is sealed with its own random IV and bound to its vault and
 *   name (additional data), so records cannot be swapped between vaults.
 * - A vault is found again by a hash of the user id (random, not personal).
 *   The phone number and name are inside the sealed "check" record only.
 * - Five wrong PINs delete the vault. Sign-out deletes it.
 *
 * Honest limit: a 4 to 6 digit PIN can be guessed offline by someone who
 * copies the browser's storage off the phone; the encryption keeps the data
 * unreadable to other people using the phone and to casual inspection, not to
 * a forensic attacker (docs/DESIGN.md).
 */
export const PBKDF2_ITERATIONS = 150_000;
export const MAX_PIN_FAILURES = 5;

interface Sealed {
  iv: Uint8Array;
  data: ArrayBuffer;
}

interface VaultRecord {
  id: string;
  /** SHA-256 of the user id, hex: finds the vault after a reload without storing who it belongs to. */
  tag: string;
  salt: Uint8Array;
  iterations: number;
  /** Sealed VaultOwner: opening it proves the PIN. */
  check: Sealed;
  failures: number;
  createdAt: number;
  usedAt: number;
}

interface ItemRecord {
  vault: string;
  name: string;
  sealed: Sealed;
}

interface VaultDB extends DBSchema {
  vaults: { key: string; value: VaultRecord; indexes: { tag: string } };
  items: { key: [string, string]; value: ItemRecord; indexes: { vault: string } };
}

/** Who a vault belongs to: enough to run the app offline after an offline sign-in. */
export interface VaultOwner {
  identifier: string;
  user: AuthOut['user'];
  active: AuthOut['active'];
  memberships: AuthOut['memberships'];
}

/**
 * none: no vault for the person signed in (or the browser cannot encrypt);
 * locked: a vault exists and the PIN is needed; open: the key is in memory.
 */
export type VaultState = 'none' | 'locked' | 'open';
export const vaultState = signal<VaultState>('none');
/** Why the vault is locked, for the unlock screen. */
export const lockReason = signal<'reload' | 'idle' | null>(null);

let current: { id: string; key: CryptoKey; owner: VaultOwner } | null = null;
const openHandlers = new Set<() => void>();

/** Run when a vault opens (after sign-in or unlock): the outbox loads and resumes. */
export function onVaultOpen(handler: () => void): () => void {
  openHandlers.add(handler);
  return () => openHandlers.delete(handler);
}

export function vaultSupported(): boolean {
  return typeof indexedDB !== 'undefined' && typeof crypto !== 'undefined' && crypto.subtle !== undefined;
}

let dbPromise: Promise<IDBPDatabase<VaultDB>> | null = null;
function db(): Promise<IDBPDatabase<VaultDB>> {
  if (!dbPromise) {
    dbPromise = openDB<VaultDB>('rahat-vault', 1, {
      upgrade(database) {
        database.createObjectStore('vaults', { keyPath: 'id' }).createIndex('tag', 'tag');
        database.createObjectStore('items', { keyPath: ['vault', 'name'] }).createIndex('vault', 'vault');
      },
    });
    dbPromise.catch(() => {
      dbPromise = null;
    });
  }
  return dbPromise;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length));
}

async function tagFor(userId: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(`rahat-vault:${userId}`));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

async function deriveKey(pin: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey('raw', encoder.encode(pin), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: salt as BufferSource, iterations },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function seal(key: CryptoKey, vault: string, name: string, plain: BufferSource): Promise<Sealed> {
  const iv = randomBytes(12);
  const data = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: iv as BufferSource, additionalData: encoder.encode(`${vault}|${name}`) },
    key,
    plain,
  );
  return { iv, data };
}

/** Throws when the key is wrong or the record was changed. */
function unseal(key: CryptoKey, vault: string, name: string, sealed: Sealed): Promise<ArrayBuffer> {
  return crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: sealed.iv as BufferSource, additionalData: encoder.encode(`${vault}|${name}`) },
    key,
    sealed.data,
  );
}

async function openWith(record: VaultRecord, pin: string): Promise<{ key: CryptoKey; owner: VaultOwner } | null> {
  const key = await deriveKey(pin, record.salt, record.iterations);
  try {
    const owner = JSON.parse(decoder.decode(await unseal(key, record.id, 'check', record.check))) as VaultOwner;
    return { key, owner };
  } catch {
    return null;
  }
}

function opened(record: VaultRecord, key: CryptoKey, owner: VaultOwner): void {
  current = { id: record.id, key, owner };
  vaultState.value = 'open';
  lockReason.value = null;
  for (const handler of openHandlers) {
    try {
      handler();
    } catch {
      // one failing listener must not stop the others
    }
  }
}

async function recordFor(userId: string): Promise<VaultRecord | undefined> {
  const database = await db();
  return database.getFromIndex('vaults', 'tag', await tagFor(userId));
}

async function deleteVault(id: string): Promise<void> {
  const database = await db();
  const tx = database.transaction(['vaults', 'items'], 'readwrite');
  const keys = await tx.objectStore('items').index('vault').getAllKeys(id);
  for (const key of keys) await tx.objectStore('items').delete(key);
  await tx.objectStore('vaults').delete(id);
  await tx.done;
}

async function countFailure(record: VaultRecord): Promise<boolean> {
  const failures = record.failures + 1;
  if (failures >= MAX_PIN_FAILURES) {
    await deleteVault(record.id);
    return true;
  }
  await (await db()).put('vaults', { ...record, failures });
  return false;
}

/**
 * After an online sign-in: open this person's vault with the PIN, or start a
 * new one. A vault that the PIN cannot open (an old PIN) cannot be read by
 * anyone, so it is replaced.
 */
export async function openAfterLogin(identifier: string, pin: string, out: AuthOut): Promise<void> {
  if (!vaultSupported()) return;
  try {
    const owner: VaultOwner = { identifier, user: out.user, active: out.active, memberships: out.memberships };
    const database = await db();
    const existing = await recordFor(out.user.id);
    if (existing) {
      const result = await openWith(existing, pin);
      if (result) {
        // Keep the owner details fresh (name, roles) for the next offline sign-in.
        const check = await seal(result.key, existing.id, 'check', encoder.encode(JSON.stringify(owner)));
        const record = { ...existing, check, failures: 0, usedAt: Date.now() };
        await database.put('vaults', record);
        opened(record, result.key, owner);
        return;
      }
      await deleteVault(existing.id);
    }
    const salt = randomBytes(16);
    const id = crypto.randomUUID();
    const key = await deriveKey(pin, salt, PBKDF2_ITERATIONS);
    const record: VaultRecord = {
      id,
      tag: await tagFor(out.user.id),
      salt,
      iterations: PBKDF2_ITERATIONS,
      check: await seal(key, id, 'check', encoder.encode(JSON.stringify(owner))),
      failures: 0,
      createdAt: Date.now(),
      usedAt: Date.now(),
    };
    await database.put('vaults', record);
    opened(record, key, owner);
  } catch {
    // Storage blocked or full: the app still works, unsent work stays in memory only.
    vaultState.value = 'none';
  }
}

/**
 * Sign in with no network: a vault on this phone that this PIN opens and that
 * belongs to this phone number. Returns its owner, or why not.
 */
export async function openOffline(identifier: string, pin: string): Promise<VaultOwner | 'wrong' | 'none'> {
  if (!vaultSupported()) return 'none';
  try {
    const records = await (await db()).getAll('vaults');
    if (records.length === 0) return 'none';
    for (const record of records) {
      const result = await openWith(record, pin);
      if (result && result.owner.identifier === identifier) {
        const fresh = { ...record, failures: 0, usedAt: Date.now() };
        await (await db()).put('vaults', fresh);
        opened(fresh, result.key, result.owner);
        return result.owner;
      }
    }
    for (const record of records) await countFailure(record);
    return 'wrong';
  } catch {
    return 'none';
  }
}

/** The PIN for the person already signed in (after a reload or an idle lock). */
export async function unlock(userId: string, pin: string): Promise<'ok' | 'wrong' | 'wiped' | 'none'> {
  try {
    const record = await recordFor(userId);
    if (!record) {
      vaultState.value = 'none';
      return 'none';
    }
    const result = await openWith(record, pin);
    if (!result || result.owner.user.id !== userId) {
      // Wiped: the gate stays shut; the caller signs the person out before anything else shows.
      return (await countFailure(record)) ? 'wiped' : 'wrong';
    }
    const fresh = { ...record, failures: 0, usedAt: Date.now() };
    await (await db()).put('vaults', fresh);
    opened(fresh, result.key, result.owner);
    return 'ok';
  } catch {
    return 'none';
  }
}

/** Is there a vault on this phone for this user? (Decides whether a restored session needs the PIN.) */
export async function hasVault(userId: string): Promise<boolean> {
  if (!vaultSupported()) return false;
  try {
    return (await recordFor(userId)) !== undefined;
  } catch {
    return false;
  }
}

/** Any vault at all on this phone (checked before the session is known, so nothing flashes before the lock). */
export async function anyVault(): Promise<boolean> {
  if (!vaultSupported()) return false;
  try {
    return (await (await db()).count('vaults')) > 0;
  } catch {
    return false;
  }
}

/** Drop the key. The sealed data stays on the phone, so nothing unsent is lost. */
export function lockVault(reason: 'reload' | 'idle'): void {
  const had = current !== null;
  current = null;
  if (had || vaultState.peek() === 'open') {
    vaultState.value = 'locked';
    lockReason.value = reason;
  }
}

export function forgetVaultState(): void {
  current = null;
  vaultState.value = 'none';
  lockReason.value = null;
}

/** Delete this person's vault (sign-out). */
export async function wipeVault(userId: string): Promise<void> {
  const mine = current;
  current = null;
  vaultState.value = 'none';
  lockReason.value = null;
  try {
    const record = mine?.owner.user.id === userId ? { id: mine.id } : await recordFor(userId);
    if (record) await deleteVault(record.id);
  } catch {
    // nothing to delete, or storage blocked
  }
}

export function vaultOwner(): VaultOwner | null {
  return current?.owner ?? null;
}

// ---- records ---------------------------------------------------------------------------------

/** Seal and store a JSON value. False when the vault is not open (the caller keeps it in memory). */
export async function putItem(name: string, value: unknown): Promise<boolean> {
  const open = current;
  if (!open) return false;
  try {
    const sealed = await seal(open.key, open.id, name, encoder.encode(JSON.stringify(value)));
    if (current !== open) return false; // locked or switched meanwhile
    await (await db()).put('items', { vault: open.id, name, sealed });
    return true;
  } catch {
    return false;
  }
}

export async function getItem<T>(name: string): Promise<T | undefined> {
  const open = current;
  if (!open) return undefined;
  try {
    const record = await (await db()).get('items', [open.id, name]);
    if (!record) return undefined;
    return JSON.parse(decoder.decode(await unseal(open.key, open.id, name, record.sealed))) as T;
  } catch {
    return undefined;
  }
}

export async function putBlob(name: string, blob: Blob): Promise<boolean> {
  const open = current;
  if (!open) return false;
  try {
    const sealed = await seal(open.key, open.id, name, await blob.arrayBuffer());
    if (current !== open) return false;
    await (await db()).put('items', { vault: open.id, name, sealed });
    return true;
  } catch {
    return false;
  }
}

export async function getBlob(name: string, type: string): Promise<Blob | undefined> {
  const open = current;
  if (!open) return undefined;
  try {
    const record = await (await db()).get('items', [open.id, name]);
    if (!record) return undefined;
    return new Blob([await unseal(open.key, open.id, name, record.sealed)], { type });
  } catch {
    return undefined;
  }
}

export async function deleteItem(name: string): Promise<void> {
  const open = current;
  if (!open) return;
  try {
    await (await db()).delete('items', [open.id, name]);
  } catch {
    // ignore
  }
}
