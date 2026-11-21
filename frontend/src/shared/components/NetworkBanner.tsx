import { t } from '../i18n';
import { online } from '../network';
import { Pictogram } from './Pictogram';

/** Always visible while offline, on every screen (citizen and staff). */
export function NetworkBanner() {
  const isOnline = online.value;
  return (
    <div role="status" aria-live="polite" class="sticky top-0 z-50">
      {isOnline ? null : (
        <p class="flex items-center justify-center gap-3 bg-ink px-4 py-2 text-base font-semibold text-white">
          <Pictogram name="offline" size={28} class="text-warning" />
          <span>{t('offline_banner')}</span>
        </p>
      )}
    </div>
  );
}
