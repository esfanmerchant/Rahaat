import { signal } from '@preact/signals';

/**
 * Browser online state. `navigator.onLine === true` only means "a network
 * exists", so treat a failed request as the real signal and use this for the
 * banner and to avoid sending work that cannot succeed.
 */
export const online = signal<boolean>(typeof navigator === 'undefined' ? true : navigator.onLine);

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    online.value = true;
  });
  window.addEventListener('offline', () => {
    online.value = false;
  });
}
