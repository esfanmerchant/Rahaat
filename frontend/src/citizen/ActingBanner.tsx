import { acting } from '../shared/acting';
import { Monogram } from '../shared/components/Monogram';
import { lang, t } from '../shared/i18n';
import { endActing } from './actingControl';

/**
 * Helper Mode: on every screen, who the helper is acting for, and the way to
 * hand the phone back. The name is server data, shown as text.
 */
export function ActingBanner() {
  const now = acting.value;
  if (!now) return null;
  const name = lang.value === 'ur' && now.nameUr ? now.nameUr : now.name;
  return (
    <div role="region" aria-label={t('helper_acting_for', { name })} class="relative z-10 border-b-4 border-info bg-info-soft text-info-strong shadow-[0_12px_32px_-10px_rgb(36_64_158/0.6)]">
      <div class="mx-auto flex w-full max-w-phone items-center gap-3 px-4 py-2">
        <span class="relative grid shrink-0 place-items-center">
          <span aria-hidden="true" class="absolute size-10 rounded-full bg-info/30 motion-safe:animate-ring" />
          <Monogram name={name} size={44} class="relative" />
        </span>
        <div class="flex min-w-0 flex-1 flex-col">
          <p class="text-lg font-bold" dir="auto">
            {t('helper_acting_for', { name })}
          </p>
          <p class="text-sm text-ink">{t('helper_banner_note')}</p>
        </div>
        <button
          type="button"
          onClick={() => void endActing('done')}
          class="inline-flex min-h-tap shrink-0 items-center rounded-full border-2 border-info-strong bg-paper px-3 text-base font-semibold text-info-strong hover:bg-surface"
        >
          {t('helper_change')}
        </button>
      </div>
    </div>
  );
}
