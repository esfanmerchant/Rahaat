import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { warmAudio } from '../shared/audio';
import { logout } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import type { ApplicationSummary, AuthUser } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Pictogram } from '../shared/components/Pictogram';
import { Spinner } from '../shared/components/Spinner';
import { lang, LANGUAGES, setLang, t, type Lang } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { draft } from './apply/flow';
import { CitizenShell } from './CitizenShell';

type Apps = { state: 'loading' } | { state: 'ready'; items: ApplicationSummary[] } | { state: 'unavailable' };

/**
 * Home after sign-in: one primary action, "Apply for Rahat" (or carry on with
 * an unfinished application), and "See my application" when one was sent.
 * The list loading or failing never blocks applying.
 */
export function HomeScreen({ user }: { user: AuthUser }) {
  const { route } = useLocation();
  const [leaving, setLeaving] = useState(false);
  const [apps, setApps] = useState<Apps>({ state: 'loading' });
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const current = lang.value;

  useEffect(() => {
    warmAudio(current);
  }, [current]);

  useEffect(() => {
    let live = true;
    void call(api.GET('/v1/applications')).then((result) => {
      if (!live) return;
      setApps(result.ok ? { state: 'ready', items: result.data.items } : { state: 'unavailable' });
    });
    return () => {
      live = false;
    };
  }, []);

  const items = apps.state === 'ready' ? apps.items : [];
  const hasDraft = draft.value !== null || items.some((item) => item.status === 'draft');
  const hasSent = items.some((item) => item.status !== 'draft' && item.status !== 'withdrawn');

  const signOut = async (): Promise<void> => {
    setLeaving(true);
    await logout(); // the "/" route then shows the start screen
  };

  const choose = (code: Lang): void => {
    setLang(code);
  };

  return (
    <CitizenShell prompt={hasDraft ? 'home_continue_hint' : 'home_apply_hint'}>
      <div class="flex items-center gap-4 pt-2">
        <Pictogram name="person" size={56} class="text-primary" />
        {/* display_name is rendered as text, never as HTML. */}
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('home_greeting', { name: user.display_name })}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t(hasDraft ? 'home_continue_hint' : 'home_apply_hint')}</p>

      <Button size="hero" icon="document" block onClick={() => route('/apply')}>
        {t(hasDraft ? 'home_continue' : 'home_apply')}
      </Button>

      <div class="flex min-h-tap-lg flex-col justify-center">
        {apps.state === 'loading' ? (
          <p role="status" class="flex items-center justify-center gap-2 text-base text-ink-muted">
            <Spinner size={24} />
            {t('state_loading')}
          </p>
        ) : hasSent ? (
          <Button size="lg" variant="secondary" icon="clock" block onClick={() => route('/track')}>
            {t('home_see_application')}
          </Button>
        ) : null}
      </div>

      <section aria-labelledby="home-language" class="mt-auto flex flex-col gap-2 pt-4">
        <h2 id="home-language" class="text-center text-base font-semibold text-ink-muted">
          {t('home_language')}
        </h2>
        <div role="radiogroup" aria-labelledby="home-language" class="grid grid-cols-2 gap-3">
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
                  'min-h-tap rounded-lg border-2 px-2 text-lg font-semibold ' +
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
        <div class="flex justify-center pt-2">
          <Button variant="quiet" size="md" busy={leaving} onClick={() => void signOut()}>
            {t('sign_out')}
          </Button>
        </div>
      </section>
    </CitizenShell>
  );
}
