import { openDB, type IDBPDatabase } from 'idb';

/**
 * Device preferences in IndexedDB. Not secret, never tokens or personal data:
 * the access token lives in memory only (see api/session.ts).
 */
export type PrefKey = 'lang' | 'pendingLogout';

const DB_NAME = 'rahat-prefs';
const STORE = 'prefs';

let dbPromise: Promise<IDBPDatabase> | null = null;

function db(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, 1, {
      upgrade(database) {
        database.createObjectStore(STORE);
      },
    });
    // Private mode or blocked storage: allow a later retry, never throw at callers.
    dbPromise.catch(() => {
      dbPromise = null;
    });
  }
  return dbPromise;
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

export async function getPref(key: PrefKey): Promise<unknown> {
  try {
    return await withTimeout(
      db().then((database) => database.get(STORE, key)),
      800,
    );
  } catch {
    return undefined;
  }
}

export async function setPref(key: PrefKey, value: unknown): Promise<void> {
  try {
    await (await db()).put(STORE, value, key);
  } catch {
    // Preferences are a convenience; losing one is acceptable.
  }
}

export async function deletePref(key: PrefKey): Promise<void> {
  try {
    await (await db()).delete(STORE, key);
  } catch {
    // ignore
  }
}
