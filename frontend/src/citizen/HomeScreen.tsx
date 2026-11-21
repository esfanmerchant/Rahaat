import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { acting } from '../shared/acting';
import { warmAudio } from '../shared/audio';
import { logout, session } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import type { ApplicationSummary, AuthUser } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Pictogram } from '../shared/components/Pictogram';
import { Spinner } from '../shared/components/Spinner';
import { lang, LANGUAGES, setLang, t, type Lang, type MessageKey } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { sayKey } from './apply/parts';
import { draft } from './apply/flow';
import { OutboxCard } from './apply/OutboxCard';
import { pendingCount, runOutbox } from './apply/outbox';
import { CitizenShell } from './CitizenShell';
import { WarningsCard } from './WarningsCard';

/** A new application is possible only after these (and a draft is carried on, not started again). */
const CLOSED_OR_DRAFT: ReadonlySet<string> = new Set(['draft', 'rejected', 'withdrawn']);

type Apps = { state: 'loading' } | { state: 'ready'; items: ApplicationSummary[] } | { state: 'unavailable' };

/**
 * Home after sign-in: one primary action, "Apply for Rahat" (or carry on with
 * an unfinished application), and "See my application" when one was sent.
 * The list loading or failing never blocks applying.
 */
export function HomeScreen({ user }: { user: AuthUser }) {
  const { route } = useLocation();
  const [leaving, setLeaving] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [apps, setApps] = useState<Apps>({ state: 'loading' });
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const current = lang.value;
  const now = session.value;
  // A helper sees the consent centre only while acting for a family; the server decides what the delegation allows.
  const isCitizen = (now.status === 'signed-in' && now.active.role === 'citizen') || acting.value !== null;
  const family = acting.value;
  const shownName = family ? (lang.value === 'ur' && family.nameUr ? family.nameUr : family.name) : user.display_name;

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
  // One open application per program (the server refuses a second): while one is open, following it is the main action.
  const hasOpen = !hasDraft && items.some((item) => !CLOSED_OR_DRAFT.has(item.status));
  const hint: MessageKey = hasOpen ? 'home_open_hint' : hasDraft ? 'home_continue_hint' : 'home_apply_hint';

  // Unsent answers live only on this phone: signing out deletes them, so ask first.
  const signOut = async (force = false): Promise<void> => {
    if (!force && pendingCount.peek() > 0) {
      setConfirmLeave(true);
      sayKey('signout_unsent_body');
      return;
    }
    setLeaving(true);
    await logout(); // the "/" route then shows the start screen
  };

  const choose = (code: Lang): void => {
    setLang(code);
  };

  return (
    <CitizenShell prompt={hint}>
      <div class="flex items-center gap-4 pt-2">
        <Pictogram name="person" size={56} class="text-primary" />
        {/* display_name is rendered as text, never as HTML. */}
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('home_greeting', { name: shownName })}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t(hint)}</p>

      {hasOpen ? (
        <Button size="hero" icon="clock" block onClick={() => route('/track')}>
          {t('home_see_application')}
        </Button>
      ) : (
        <Button size="hero" icon="document" block onClick={() => route('/apply')}>
          {t(hasDraft ? 'home_continue' : 'home_apply')}
        </Button>
      )}

      {hasOpen ? null : apps.state === 'loading' ? (
        <p role="status" class="flex min-h-tap-lg items-center justify-center gap-2 text-base text-ink-muted">
          <Spinner size={24} />
          {t('state_loading')}
        </p>
      ) : hasSent ? (
        <Button size="lg" variant="secondary" icon="clock" block onClick={() => route('/track')}>
          {t('home_see_application')}
        </Button>
      ) : null}

      {/* The shopkeeper's scam checker and the consent centre, one tap each. */}
      <div class="grid grid-cols-1 gap-3">
        <Button size="lg" variant="secondary" icon="shield" block onClick={() => route('/scam')}>
          {t('home_scam')}
        </Button>
        <Button size="lg" variant="secondary" icon="message" block onClick={() => route('/rules')}>
          {t('home_rules')}
        </Button>
        {isCitizen ? (
          <Button size="lg" variant="secondary" icon="lock" block onClick={() => route('/my-data')}>
            {t('home_my_data')}
          </Button>
        ) : null}
      </div>

      <OutboxCard />

      <WarningsCard />

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
        {family ? null : confirmLeave ? (
          <div role="alert" class="flex flex-col gap-3 rounded-lg border-2 border-danger bg-danger-soft p-3 text-danger">
            <p class="flex items-center gap-2 text-lg font-bold">
              <Pictogram name="warning" size={32} />
              {t('signout_unsent_title')}
            </p>
            <p class="text-base text-ink">{t('signout_unsent_body')}</p>
            <Button
              size="md"
              icon="sending"
              block
              onClick={() => {
                setConfirmLeave(false);
                void runOutbox();
              }}
            >
              {t('signout_unsent_stay')}
            </Button>
            <Button size="md" variant="danger" icon="delete" block busy={leaving} onClick={() => void signOut(true)}>
              {t('signout_unsent_go')}
            </Button>
          </div>
        ) : (
          <div class="flex justify-center pt-2">
            <Button variant="quiet" size="md" busy={leaving} onClick={() => void signOut()}>
              {t('sign_out')}
            </Button>
          </div>
        )}
      </section>
    </CitizenShell>
  );
}
