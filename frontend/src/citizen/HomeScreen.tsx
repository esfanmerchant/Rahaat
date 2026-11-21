import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { acting } from '../shared/acting';
import { warmAudio } from '../shared/audio';
import { logout, session } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import type { ApplicationSummary, AuthUser } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Monogram } from '../shared/components/Monogram';
import { Pictogram, type PictogramName } from '../shared/components/Pictogram';
import { SoundToggle } from '../shared/components/SoundToggle';
import { Spinner } from '../shared/components/Spinner';
import { lang, LANGUAGES, setLang, t, type Lang, type MessageKey } from '../shared/i18n';
import { go } from '../shared/routing';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { endActing } from './actingControl';
import { Journey } from './Journey';
import { PaidCard } from './PaidCard';
import { setJourney } from './journeyStore';
import { StarBullet } from './JourneyPath';
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
      if (result.ok) setJourney(result.data.items);
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

  const hour = new Date().getHours();
  const greeting: MessageKey = hour < 12 ? 'greeting_morning' : hour < 17 ? 'greeting_afternoon' : 'greeting_evening';
  const latest = items.find((item) => item.status !== 'withdrawn');

  const hero = (
    <div class="flex flex-col gap-4 pt-1">
      <div class="flex items-center gap-4">
        <Monogram name={shownName} size={64} />
        {/* display_name is rendered as text, never as HTML. */}
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-extrabold text-night-ink lg:text-3xl lg:text-ink">
          {t(greeting, { name: shownName })}
        </h1>
      </div>
      <div class="lg:hidden">
        {apps.state === 'loading' ? (
          <p role="status" class="flex min-h-tap-lg items-center justify-center gap-2 text-base text-night-muted">
            <Spinner size={24} />
            {t('state_loading')}
          </p>
        ) : (
          <Journey status={latest?.status ?? null} bare />
        )}
      </div>
    </div>
  );

  return (
    <CitizenShell prompt={hint} hero={hero} surface="bare">
      <div class="rh-stagger flex flex-col gap-6 lg:gap-8">
      {latest?.status === 'paid' ? <PaidCard /> : null}
      <p class="text-lg text-ink-muted lg:text-xl">{t(hint)}</p>

      {hasOpen ? (
        <Button size="hero" icon="clock" block onClick={() => go(route, '/track')}>
          {t('home_see_application')}
        </Button>
      ) : (
        <Button size="hero" icon="document" block onClick={() => go(route, '/apply')}>
          {t(hasDraft ? 'home_continue' : 'home_apply')}
        </Button>
      )}

      {apps.state === 'loading' ? (
        <p role="status" class="hidden min-h-tap-lg items-center justify-center gap-2 text-base text-ink-muted lg:flex">
          <Spinner size={24} />
          {t('state_loading')}
        </p>
      ) : null}

      <div class="grid grid-cols-2 gap-3 lg:grid-cols-3 lg:gap-4 [&>:last-child:nth-child(odd)]:col-span-2 lg:[&>:last-child:nth-child(odd)]:col-span-1">
        {hasSent && !hasOpen ? <Tile icon="clock" tone="primary" label={t('home_see_application')} onClick={() => go(route, '/track')} /> : null}
        <Tile icon="shield" tone="primary" label={t('home_scam')} onClick={() => go(route, '/scam')} />
        <Tile icon="message" tone="info" label={t('home_rules')} onClick={() => go(route, '/rules')} />
        <Tile icon="warning" tone="info" label={t('home_report')} onClick={() => go(route, '/report')} />
        {isCitizen ? <Tile icon="lock" tone="saffron" label={t('home_my_data')} onClick={() => go(route, '/my-data')} /> : null}
        {family ? <Tile icon="person-help" tone="info" label={t('helper_change')} onClick={() => void endActing('done')} /> : null}
      </div>

      <OutboxCard />

      <WarningsCard />

      <section aria-labelledby="home-language" class="flex flex-col gap-2 pt-4">
        <h2 id="home-language" class="flex items-center justify-center gap-2 text-base font-semibold text-ink-muted">
          <StarBullet class="text-noor-strong" />
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
        <SoundToggle />
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
      </div>
    </CitizenShell>
  );
}

const TINT = {
  primary: 'bg-primary/10 text-primary',
  info: 'bg-info/10 text-info',
  saffron: 'bg-warning/20 text-warning-ink',
} as const;

/** A big action tile: one pictogram in a soft tinted circle, one word, at least 112 px tall. Lifts on hover, springs on press. */
function Tile({ icon, label, tone, onClick }: { icon: PictogramName; label: string; tone: keyof typeof TINT; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      class="rh-tile flex min-h-28 flex-col items-center justify-center gap-3 rounded-2xl border border-line bg-paper p-4 text-center text-lg font-bold text-ink shadow-lift lg:min-h-36"
    >
      <span class={`grid size-16 place-items-center rounded-full ${TINT[tone]}`}>
        <Pictogram name={icon} size={44} />
      </span>
      {label}
    </button>
  );
}
