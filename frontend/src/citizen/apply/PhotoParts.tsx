import { useEffect, useRef } from 'preact/hooks';
import { Button } from '../../shared/components/Button';
import { Spinner } from '../../shared/components/Spinner';
import { t, type MessageKey } from '../../shared/i18n';
import { drawPreview } from './photo';

interface PhotoButtonsProps {
  onFile: (file: File | undefined) => void;
  /** Label of the camera button: "Take a photo" or "Take it again". */
  takeLabel?: MessageKey;
  disabled?: boolean;
  /** One quiet camera button, when another action is the primary one. */
  quiet?: boolean;
}

/**
 * Camera first, file picker as fallback. `capture` opens the phone's own
 * camera app, so the page needs no camera permission; a desktop browser
 * shows its file picker instead.
 */
export function PhotoButtons({ onFile, takeLabel = 'card_take', disabled = false, quiet = false }: PhotoButtonsProps) {
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const picked = (event: Event): void => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // the same photo can be picked again
    onFile(file);
  };
  return (
    <div class="flex flex-col gap-3">
      <input ref={camera} type="file" accept="image/*" capture="environment" class="hidden" onChange={picked} tabIndex={-1} aria-hidden="true" />
      <input ref={picker} type="file" accept="image/*" class="hidden" onChange={picked} tabIndex={-1} aria-hidden="true" />
      <Button
        size={quiet ? 'md' : 'lg'}
        variant={quiet ? 'secondary' : 'primary'}
        icon="camera"
        block
        disabled={disabled}
        onClick={() => camera.current?.click()}
      >
        {t(takeLabel)}
      </Button>
      {quiet ? null : (
        <Button size="md" variant="secondary" icon="document" block disabled={disabled} onClick={() => picker.current?.click()}>
          {t('card_choose')}
        </Button>
      )}
    </div>
  );
}

/** The resized photo, drawn on a canvas (no blob: URL, so img-src stays 'self'). */
export function PhotoPreview({ source, busy, label }: { source: HTMLCanvasElement | null; busy?: string | undefined; label: string }) {
  const target = useRef<HTMLCanvasElement>(null);
  useEffect(() => drawPreview(target.current, source), [source]);
  if (!source) return null;
  return (
    <figure class="relative overflow-hidden rounded-lg border-2 border-line-strong bg-sunken">
      <canvas ref={target} role="img" aria-label={label} class="block h-auto max-h-56 w-full object-contain" />
      {busy ? (
        <figcaption role="status" class="flex items-center justify-center gap-3 bg-paper px-3 py-2 text-lg text-ink">
          <Spinner size={28} class="text-primary" />
          <span>{busy}</span>
        </figcaption>
      ) : null}
    </figure>
  );
}
