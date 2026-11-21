import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { logout } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { AuthUser, FamilyOut } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { lang, t, type Key } from '../../shared/i18n';
import '../../shared/i18n/more';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { handedBack } from '../actingControl';
import { sayKey, Notice } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { statusIcon, statusKey } from '../result/data';
import { FamilyPin } from './FamilyPin';

type Loaded =
  | { state: 'loading' }
  | { state: 'failed'; failure: ApiFailure }
  | { state: 'ready'; items: FamilyOut[]; next: string | null };

/** The name to show for the language in use, and the other one under it. */
export function namesOf(family: FamilyOut): { main: string; other: string | null; mainLang: 'ur' | 'en'; otherLang: 'ur' | 'en' } {
  const en = family.display_name ?? '';
  const ur = family.display_name_ur ?? '';
  const wantUr = lang.value === 'ur';
  const main = (wantUr ? ur || en : en || ur) || '-';
  const other = (wantUr ? en : ur) || null;
  const mainIsUr = wantUr ? Boolean(ur) : !en;
  return { main, other: other && other !== main ? other : null, mainLang: mainIsUr ? 'ur' : 'en', otherLang: mainIsUr ? 'en' : 'ur' };
}

function Chip({ icon, text, tone = 'border-line-strong bg-paper text-ink' }: { icon: Parameters<typeof Pictogram>[0]['name']; text: string; tone?: string }) {
  return (
    <span class={`inline-flex items-center gap-1 rounded-full border-2 px-2 py-1 text-base font-semibold ${tone}`}>
      <Pictogram name={icon} size={24} />
      {text}
    </span>
  );
}

function FamilyCard({ family, onPick }: { family: FamilyOut; onPick: () => void }) {
  const names = namesOf(family);
  const live = family.delegation_status === 'live';
  const app = family.application;
  const delegationText: Key = live ? 'helper_may_help' : family.delegation_status === 'revoked' ? 'helper_stopped' : 'helper_ended';
  return (
    <li>
      <button
        type="button"
        disabled={!live}
        onClick={onPick}
        class="flex w-full flex-col gap-3 rounded-lg border-2 border-line-strong bg-paper p-3 text-start hover:bg-surface disabled:cursor-not-allowed disabled:bg-sunken"
      >
        <span class="flex items-center gap-3">
          <Pictogram name="person" size={48} class={live ? 'text-primary' : 'text-ink-muted'} />
          <span class="flex min-w-0 flex-1 flex-col">
            {/* Names are server data: text, each in its own language and direction. */}
            <span class="text-xl font-bold" lang={names.mainLang} dir={names.mainLang === 'ur' ? 'rtl' : 'ltr'}>
              {names.main}
            </span>
            {names.other ? (
              <span class="text-base text-ink-muted" lang={names.otherLang} dir={names.otherLang === 'ur' ? 'rtl' : 'ltr'}>
                {names.other}
              </span>
            ) : null}
            {family.district ? <span class="text-base text-ink-muted">{family.district}</span> : null}
          </span>
          {live ? <Pictogram name="forward" size={32} class="shrink-0 text-ink-muted" /> : null}
        </span>
        <span class="flex flex-wrap gap-2">
          <Chip
            icon={app ? statusIcon(app.status) : 'document'}
            text={app ? t(statusKey(app.status)) : t('helper_app_none')}
            tone="border-line-strong bg-surface text-ink"
          />
          <Chip
            icon={family.consent_active ? 'yes' : 'pause'}
            text={t(family.consent_active ? 'helper_consent_on' : 'helper_consent_off')}
            tone={family.consent_active ? 'border-primary bg-primary-soft text-primary-strong' : 'border-warning bg-warning-soft text-warning-ink'}
          />
          <Chip
            icon={live ? 'person-help' : 'lock'}
            text={t(delegationText)}
            tone={live ? 'border-info bg-info-soft text-info-strong' : 'border-line-strong bg-surface text-ink'}
          />
        </span>
      </button>
    </li>
  );
}

/**
 * Helper Mode, step one: the helper's families as large cards with search.
 * Tapping a family asks for that family's PIN (FamilyPin). Nothing of any
 * family is in memory here except what the list itself shows.
 */
export default function HelperFamilies({ user }: { user: AuthUser }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [more, setMore] = useState(false);
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<FamilyOut | null>(null);
  const [leaving, setLeaving] = useState(false);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(loaded.state === 'ready' && picked === null);
  const note = handedBack.value;

  useEffect(() => {
    let live = true;
    setLoaded({ state: 'loading' });
    void call(api.GET('/v1/helper/families', { params: { query: { limit: 50 } } })).then((result) => {
      if (!live) return;
      setLoaded(result.ok ? { state: 'ready', items: result.data.items, next: result.data.next_cursor ?? null } : { state: 'failed', failure: result.failure });
    });
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(() => {
    if (note) sayKey(note === 'idle' ? 'helper_handed_idle' : 'helper_handed_expired');
  }, [note]);

  const showMore = async (): Promise<void> => {
    if (loaded.state !== 'ready' || !loaded.next) return;
    setMore(true);
    const result = await call(api.GET('/v1/helper/families', { params: { query: { limit: 50, cursor: loaded.next } } }));
    setMore(false);
    if (result.ok) setLoaded({ state: 'ready', items: [...loaded.items, ...result.data.items], next: result.data.next_cursor ?? null });
  };

  const shown = useMemo(() => {
    if (loaded.state !== 'ready') return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return loaded.items;
    return loaded.items.filter((f) => [f.display_name, f.display_name_ur, f.district].some((v) => v?.toLowerCase().includes(needle)));
  }, [loaded, query]);

  const signOut = useCallback(() => {
    setLeaving(true);
    // The families' unsent answers stay sealed on the phone for this helper.
    void logout({ keepVault: true });
  }, []);

  if (picked) {
    const names = namesOf(picked);
    return (
      <FamilyPin
        family={{ personId: picked.person_id, name: picked.display_name ?? names.main, nameUr: picked.display_name_ur ?? null }}
        shownName={names.main}
        onBack={() => setPicked(null)}
      />
    );
  }

  return (
    <CitizenShell prompt="helper_prompt">
      <div class="flex items-center gap-4 pt-2">
        <Pictogram name="family" size={56} class="text-primary" />
        <div class="flex min-w-0 flex-col">
          <p class="text-lg text-ink-muted" dir="auto">
            {t('home_greeting', { name: user.display_name })}
          </p>
          <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
            {t('helper_title')}
          </h1>
        </div>
      </div>
      <p class="text-lg text-ink-muted">{t('helper_prompt')}</p>
      {note ? <Notice tone="warn" icon="clock" text={t(note === 'idle' ? 'helper_handed_idle' : 'helper_handed_expired')} /> : null}

      {loaded.state === 'loading' ? <ScreenState kind="loading" /> : null}
      {loaded.state === 'failed' ? <FailureState failure={loaded.failure} onRetry={() => setAttempt((n) => n + 1)} /> : null}
      {loaded.state === 'ready' && loaded.items.length === 0 ? (
        <ScreenState kind="empty" heading="h2" title={t('helper_empty_title')} body={t('helper_empty_body')} />
      ) : null}
      {loaded.state === 'ready' && loaded.items.length > 0 ? (
        <>
          <label class="flex flex-col gap-1 text-base font-semibold text-ink-muted">
            {t('helper_search')}
            <input
              type="search"
              value={query}
              onInput={(event) => setQuery((event.target as HTMLInputElement).value)}
              autoComplete="off"
              class="min-h-tap-lg rounded-lg border-2 border-line-strong bg-paper px-3 text-xl font-normal text-ink"
            />
          </label>
          <p class="text-base text-ink-muted" role="status">
            {t('helper_count', { count: shown.length })}
          </p>
          {shown.length === 0 ? (
            <p role="status" class="py-6 text-center text-xl text-ink-muted">
              {t('helper_no_match')}
            </p>
          ) : (
            <ul class="flex flex-col gap-3">
              {shown.map((family) => (
                <FamilyCard key={family.person_id} family={family} onPick={() => setPicked(family)} />
              ))}
            </ul>
          )}
          {loaded.next ? (
            <Button size="md" variant="neutral" icon="plus" block busy={more} onClick={() => void showMore()}>
              {t('helper_load_more')}
            </Button>
          ) : null}
        </>
      ) : null}

      <div class="mt-auto flex justify-center pt-4">
        <Button variant="quiet" size="md" busy={leaving} onClick={signOut}>
          {t('sign_out')}
        </Button>
      </div>
    </CitizenShell>
  );
}
