import { useLocation } from 'preact-iso';
import { playPrompt, unlockAudio, warmAudio } from '../shared/audio';
import { Button } from '../shared/components/Button';
import { RahatMark } from '../shared/components/RahatMark';
import { lang, LANGUAGES, setLang, t, type Lang } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { CitizenShell } from './CitizenShell';

/**
 * First screen: one large start button and a language choice. Browsers block
 * sound until the first tap, so both the start button and the language
 * buttons unlock audio.
 */
export function StartScreen() {
  const { route } = useLocation();
  const current = lang.value;
  const headingRef = useFocusOnMount<HTMLHeadingElement>();

  const start = (): void => {
    unlockAudio();
    warmAudio(current); // fill the offline audio cache in the background
    route('/login');
  };

  const choose = (code: Lang): void => {
    unlockAudio();
    setLang(code);
    playPrompt('start_hint', code, t('start_hint', undefined, code));
  };

  return (
    <CitizenShell prompt="start_hint" autoPlay={false}>
      <div class="flex flex-col items-center gap-3 pt-4 text-center">
        <RahatMark size={88} />
        <h1 ref={headingRef} tabIndex={-1} class="text-3xl font-bold">
          {t('program_name')}
        </h1>
        <p class="text-lg text-ink-muted">{t('program_tagline')}</p>
      </div>

      <Button size="hero" icon="forward" block onClick={start}>
        {t('start_button')}
      </Button>
      <p class="text-center text-lg text-ink-muted">{t('start_hint')}</p>

      <section aria-labelledby="choose-language" class="mt-auto flex flex-col gap-3">
        <h2 id="choose-language" class="text-center text-lg font-semibold">
          {t('choose_language')}
        </h2>
        <div role="radiogroup" aria-labelledby="choose-language" class="grid grid-cols-2 gap-3">
          {LANGUAGES.map((option) => {
            const selected = option.code === current;
            return (
              <button
                key={option.code}
                type="button"
                role="radio"
                aria-checked={selected}
                lang={option.code}
                dir={option.dir}
                onClick={() => choose(option.code)}
                class={
                  'min-h-tap-lg rounded-lg border-2 px-2 text-xl font-semibold ' +
                  (selected
                    ? 'border-primary bg-primary-soft text-primary-strong'
                    : 'border-line-strong bg-paper text-ink hover:bg-surface')
                }
              >
                {option.native}
              </button>
            );
          })}
        </div>
      </section>
    </CitizenShell>
  );
}
