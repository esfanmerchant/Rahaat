import { useLocation } from 'preact-iso';
import { playPrompt, unlockAudio, warmAudio } from '../shared/audio';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Emblem } from '../shared/components/Emblem';
import { Pictogram } from '../shared/components/Pictogram';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { celebrate } from '../shared/feedback';
import { lang, LANGUAGES, setLang, t, type Lang } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { HomeLights } from './HomeLights';

/**
 * First screen: a night sky with the emblem drawing itself, one large start button and a language choice.
 * Browsers block sound until the first tap, so the start button and the language buttons unlock audio; the
 * start tap also rings the chime.
 */
export function StartScreen() {
  const { route } = useLocation();
  const current = lang.value;
  const headingRef = useFocusOnMount<HTMLHeadingElement>();

  const start = (): void => {
    unlockAudio();
    celebrate();
    warmAudio(current); // fill the offline audio cache in the background
    route('/login');
  };

  const choose = (code: Lang): void => {
    unlockAudio();
    setLang(code);
    playPrompt('start_hint', code, t('start_hint', undefined, code));
  };

  return (
    <div class="rh-night-sky relative flex min-h-dvh flex-col overflow-hidden">
      <div aria-hidden="true" class="rh-lattice-night absolute inset-0 opacity-80" />
      <HomeLights />
      <div class="relative mx-auto flex w-full max-w-phone flex-1 flex-col px-5 pt-3 pb-4 md:max-w-xl">
        <div class="flex justify-end">
          <AudioPrompt prompt="start_hint" autoPlay={false} tone="night" />
        </div>

        <main id="main" class="flex flex-1 flex-col items-center justify-center gap-3 py-2 text-center">
          <div class="relative grid place-items-center">
            <span aria-hidden="true" class="absolute size-[clamp(140px,32dvh,240px)] rounded-full bg-noor/20 blur-md motion-safe:animate-float" />
            <Emblem size={150} tone="night" animate class="relative size-[clamp(96px,22dvh,176px)]" />
          </div>
          <h1 ref={headingRef} tabIndex={-1} class="flex flex-col items-center gap-0">
            <span lang="ur" dir="rtl" class="text-5xl font-black text-noor motion-safe:animate-rise" style={{ animationDelay: '300ms' }}>
              راحت
            </span>
            <span lang="en" dir="ltr" class="text-3xl font-black tracking-tight text-night-ink motion-safe:animate-rise" style={{ animationDelay: '420ms' }}>
              Rahat
            </span>
          </h1>
          <p class="max-w-sm text-lg text-night-muted motion-safe:animate-rise" style={{ animationDelay: '540ms' }}>
            {t('program_tagline')}
          </p>
        </main>

        <div class="flex flex-col items-stretch gap-3 motion-safe:animate-rise" style={{ animationDelay: '700ms' }}>
          <div class="relative">
            <span aria-hidden="true" class="absolute inset-0 rounded-lg border-2 border-noor hidden motion-safe:block motion-safe:animate-ring" />
            <button
              type="button"
              onClick={start}
              class="relative inline-flex min-h-tap-xl w-full items-center justify-center gap-4 rounded-lg border-2 border-noor bg-primary px-6 py-3 text-2xl font-bold text-white shadow-glow transition-transform duration-100 active:scale-[0.97]"
            >
              <Pictogram name="forward" size={48} />
              {t('start_button')}
            </button>
          </div>
          <p class="text-center text-lg text-night-muted">{t('start_hint')}</p>

          <section aria-labelledby="choose-language" class="flex flex-col gap-2">
            <h2 id="choose-language" class="text-center text-base font-semibold text-night-muted">
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
                      'min-h-tap rounded-full border-2 px-2 text-xl font-semibold transition-colors duration-100 ' +
                      (selected ? 'border-noor bg-noor text-night' : 'border-night-line bg-night-2 text-night-ink hover:bg-night-3')
                    }
                  >
                    {option.native}
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      </div>
      <div class="relative">
        <PrototypeFooter tone="night" />
      </div>
    </div>
  );
}
