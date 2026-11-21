import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { onSessionEnd } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import type { ScamWarning } from '../shared/api/types';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Pictogram } from '../shared/components/Pictogram';
import { dirOf, lang, t, type Lang } from '../shared/i18n';
import { online } from '../shared/network';

/** Public warnings for the person's area, loaded once per session (memory only). */
const warnings = signal<ScamWarning[] | null>(null);
let loading = false;
/** Set once the home screen asked: before that there may be no session to ask with. */
let loadedOnce = false;

onSessionEnd(() => {
  warnings.value = null;
  loading = false;
  loadedOnce = false;
});

async function loadWarnings(): Promise<void> {
  if (loading || warnings.peek() !== null) return;
  loading = true;
  // The person's district narrows the list to their area; a helper without a person sees the department's.
  const person = await call(api.GET('/v1/me/person'));
  const district = person.ok ? person.data.district : null;
  const query: { limit: number; district?: string } = { limit: 3 };
  if (district) query.district = district;
  const result = await call(api.GET('/v1/scam/warnings', { params: { query } }));
  loading = false;
  if (result.ok) warnings.value = result.data.items;
}

// Offline at first: try again when the network is back (only while signed in: the API needs a session).
online.subscribe((isOnline) => {
  if (isOnline && warnings.peek() === null && !loading && loadedOnce) void loadWarnings();
});

/** The warning's text in the person's language when the officer wrote one, else in English. */
function bodyOf(item: ScamWarning, code: Lang): { text: string; lang: Lang } {
  if (code === 'ur' && item.body_ur) return { text: item.body_ur, lang: 'ur' };
  return { text: item.body_en, lang: 'en' };
}

/**
 * Scam warnings on the home screen: short, with a speaker. The officer's words
 * have no recording, so the speaker says our own fixed warning, then their
 * words with a device voice where one exists, then "Rahat never asks for a fee".
 * Nothing shows while loading, offline or when there is no warning.
 */
export function WarningsCard() {
  const code = lang.value;
  useEffect(() => {
    loadedOnce = true;
    void loadWarnings();
  }, []);
  const items = warnings.value ?? [];
  if (items.length === 0) return null;
  const shown = items.slice(0, 2);
  const speech = {
    id: `warnings:${shown.map((item) => item.id).join(',')}:${code}`,
    items: [
      { key: 'warn_prompt', text: t('warn_prompt', undefined, code) },
      ...shown.map((item, index) => {
        const body = bodyOf(item, code);
        return { key: `warning.${index}`, text: body.text, lang: body.lang };
      }),
      { key: 'scam_never_pay', text: t('scam_never_pay', undefined, code) },
    ],
    lang: code,
  };
  return (
    <section aria-labelledby="home-warnings" class="flex flex-col gap-3 rounded-2xl border-2 border-warning bg-warning-soft p-4 text-warning-ink shadow-lift">
      <div class="flex items-center justify-between gap-2">
        <h2 id="home-warnings" class="flex items-center gap-2 text-xl font-bold">
          <Pictogram name="warning" size={36} />
          {t('warn_title')}
        </h2>
        <AudioPrompt speech={speech} />
      </div>
      <ul class="flex flex-col gap-2">
        {shown.map((item) => {
          const body = bodyOf(item, code);
          return (
            // Officer-written text: shown as text, never HTML, in its own language and direction.
            <li key={item.id} lang={body.lang} dir={dirOf(body.lang)} class="flex flex-col gap-1">
              {body.lang === 'en' ? <p class="text-base font-bold text-ink">{item.title}</p> : null}
              <p class="text-base text-ink">{body.text}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
