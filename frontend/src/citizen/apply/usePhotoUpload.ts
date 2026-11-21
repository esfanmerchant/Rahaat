import { useEffect, useRef, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import type { DocumentKind, DocumentView } from '../../shared/api/types';
import { online } from '../../shared/network';
import { queuePhoto } from './flow';
import { ops, opResults, sendingId } from './outbox';
import { preparePhoto, type PreparedPhoto } from './photo';

export type PhotoPhase =
  | { name: 'idle' }
  | { name: 'preparing' }
  | { name: 'sending' }
  /** No network: the photo waits in the outbox (sealed on the phone) and goes when the network is back. */
  | { name: 'stored' }
  | { name: 'failed'; failure: ApiFailure }
  | { name: 'unreadable' }
  | { name: 'result'; doc: DocumentView };

/**
 * Pick or take a photo, resize it on the device, and put it in the outbox.
 * The phase follows the outbox: sending, saved on this phone, or the server's
 * answer. A retry after a failure queues the same photo again.
 */
export function usePhotoUpload(kind: DocumentKind, onResult: (doc: DocumentView) => void, applicationId?: string) {
  const [local, setLocal] = useState<'idle' | 'preparing' | 'unreadable'>('idle');
  const [opId, setOpId] = useState<string | null>(null);
  const photo = useRef<PreparedPhoto | null>(null);
  const answered = useRef<string | null>(null);

  const result = opId ? opResults.value.get(opId) : undefined;
  const queued = opId ? ops.value.find((op) => op.id === opId) : undefined;
  const isOnline = online.value;
  const sendingNow = queued !== undefined && sendingId.value === queued.id;

  useEffect(() => {
    if (!opId || result?.state !== 'done' || answered.current === opId) return;
    answered.current = opId;
    onResult(result.result as DocumentView);
  }, [opId, result]);

  let phase: PhotoPhase;
  if (local === 'preparing') phase = { name: 'preparing' };
  else if (local === 'unreadable') phase = { name: 'unreadable' };
  else if (result?.state === 'done') phase = { name: 'result', doc: result.result as DocumentView };
  else if (result?.state === 'failed') phase = { name: 'failed', failure: result.failure };
  else if (queued) phase = sendingNow || (isOnline && queued.tries === 0) ? { name: 'sending' } : { name: 'stored' };
  else phase = { name: 'idle' };

  const send = (): void => {
    const prepared = photo.current;
    if (!prepared) return;
    setOpId(queuePhoto(prepared.blob, kind, applicationId).id);
  };

  const choose = async (file: File | undefined): Promise<void> => {
    if (!file) return;
    setLocal('preparing');
    setOpId(null);
    try {
      photo.current = await preparePhoto(file);
    } catch {
      setLocal('unreadable');
      return;
    }
    setLocal('idle');
    send();
  };

  const reset = (): void => {
    photo.current = null;
    setOpId(null);
    setLocal('idle');
  };

  return { phase, choose, retry: send, reset, preview: photo.current?.canvas ?? null };
}
