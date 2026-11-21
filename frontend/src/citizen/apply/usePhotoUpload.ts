import { useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import type { DocumentKind, DocumentView } from '../../shared/api/types';
import { online } from '../../shared/network';
import { newId, uploadPhoto } from './flow';
import { preparePhoto, type PreparedPhoto } from './photo';

export type PhotoPhase =
  | { name: 'idle' }
  | { name: 'preparing' }
  | { name: 'sending' }
  | { name: 'waiting' } // offline: the photo is kept in memory and sent when the network is back
  | { name: 'failed'; failure: ApiFailure }
  | { name: 'unreadable' }
  | { name: 'result'; doc: DocumentView };

/**
 * Pick or take a photo, resize it on the device, upload it. The photo stays in
 * memory only. A retry sends the same photo with the same Idempotency-Key.
 */
export function usePhotoUpload(kind: DocumentKind, onResult: (doc: DocumentView) => void, applicationId?: string) {
  const [phase, setPhase] = useState<PhotoPhase>({ name: 'idle' });
  const photo = useRef<PreparedPhoto | null>(null);
  const key = useRef(newId());
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const send = async (): Promise<void> => {
    const prepared = photo.current;
    if (!prepared) return;
    if (!online.peek()) {
      setPhase({ name: 'waiting' });
      return;
    }
    setPhase({ name: 'sending' });
    const result = await uploadPhoto(prepared.blob, kind, key.current, applicationId);
    if (!alive.current) return;
    if (result.ok) {
      setPhase({ name: 'result', doc: result.data });
      onResult(result.data);
    } else if (result.failure.kind === 'offline') {
      setPhase({ name: 'waiting' });
    } else {
      setPhase({ name: 'failed', failure: result.failure });
    }
  };

  // Offline when the photo was taken: send it as soon as the network is back.
  useEffect(() => {
    if (phase.name !== 'waiting') return undefined;
    return online.subscribe((isOnline) => {
      if (isOnline) void send();
    });
  }, [phase.name]);

  const choose = async (file: File | undefined): Promise<void> => {
    if (!file) return;
    setPhase({ name: 'preparing' });
    try {
      photo.current = await preparePhoto(file);
    } catch {
      if (alive.current) setPhase({ name: 'unreadable' });
      return;
    }
    key.current = newId(); // a new photo is a new upload
    await send();
  };

  const reset = (): void => {
    photo.current = null;
    setPhase({ name: 'idle' });
  };

  return { phase, choose, retry: send, reset, preview: photo.current?.canvas ?? null };
}
