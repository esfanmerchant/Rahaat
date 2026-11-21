import { setSound, soundOn } from '../feedback';
import { t } from '../i18n';
import { Pictogram } from './Pictogram';

/** Turns the chime and the vibration on or off (stored on this phone). The voice prompts have their own button. */
export function SoundToggle() {
  const on = soundOn.value;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setSound(!on)}
      class="mx-auto inline-flex min-h-tap items-center gap-2 rounded-full border-2 border-line-strong bg-paper px-4 text-base font-semibold text-ink hover:bg-surface"
    >
      <Pictogram name="speaker" size={28} class={on ? 'text-primary' : 'text-ink-subtle'} />
      {on ? t('sound_on') : t('sound_off')}
    </button>
  );
}
