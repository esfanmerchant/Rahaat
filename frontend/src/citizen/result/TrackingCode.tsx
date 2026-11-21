import type { SpeechItem } from '../../shared/audio';
import { AudioPrompt } from '../../shared/components/AudioPrompt';
import { Pictogram, pictogramFor } from '../../shared/components/Pictogram';
import { isMessageKey, lang, t } from '../../shared/i18n';
import { numberKey } from '../apply/parts';

/**
 * The symbol tracking code (PLAN 3, item 7): three pictures and a number, so a
 * person who cannot read can still recognise and say it. The button reads it out.
 */
export function TrackingCode({ code, symbols }: { code: string | null | undefined; symbols: readonly string[] }) {
  const ui = lang.value;
  const pictures = symbols.map((name) => ({ name, icon: pictogramFor(name), key: `sym_${name}` }));
  if (!code && pictures.length === 0) return null;

  const items: SpeechItem[] = [{ key: 'track_code_intro', text: t('track_code_intro', undefined, ui) }];
  for (const picture of pictures) {
    if (isMessageKey(picture.key)) items.push({ key: picture.key, text: t(picture.key, undefined, ui) });
  }
  for (const char of code ?? '') {
    const key = numberKey(Number.parseInt(char, 10));
    if (/\d/.test(char) && key) items.push({ key, text: t(key, undefined, ui) });
  }

  return (
    <section aria-labelledby="track-code" class="flex flex-col gap-3 rounded-lg border-2 border-primary bg-primary-soft p-4">
      <h2 id="track-code" class="text-lg font-semibold text-primary-strong">
        {t('track_code')}
      </h2>
      <ul class="flex items-start justify-center gap-4">
        {pictures.map((picture, index) => (
          <li key={`${picture.name}-${index}`} class="flex flex-col items-center gap-1">
            <span class="flex size-20 items-center justify-center rounded-lg border-2 border-primary bg-paper text-primary-strong">
              {picture.icon ? <Pictogram name={picture.icon} size={56} /> : <Pictogram name="unknown" size={56} />}
            </span>
            <span class="text-base font-semibold text-ink">
              {isMessageKey(picture.key) ? t(picture.key) : picture.name}
            </span>
          </li>
        ))}
      </ul>
      {code ? (
        <p class="rh-ltr text-center font-mono text-3xl font-bold tracking-wider text-ink">{code}</p>
      ) : null}
      <p class="text-center text-base text-ink-muted">{t('track_code_hint')}</p>
      <div class="flex justify-center">
        <AudioPrompt speech={{ id: `code:${code ?? ''}:${symbols.join(',')}:${ui}`, items, lang: ui }} label={t('track_hear_code')} />
      </div>
    </section>
  );
}
