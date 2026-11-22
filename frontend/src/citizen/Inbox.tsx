import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { acting } from '../shared/acting';
import { onSessionEnd, session } from '../shared/api/auth';
import { api } from '../shared/api/client';
import { call, type ApiFailure } from '../shared/api/problem';
import type { NotificationOut } from '../shared/api/types';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Button } from '../shared/components/Button';
import { Pictogram } from '../shared/components/Pictogram';
import { FailureState, ScreenState } from '../shared/components/ScreenState';
import { lang, t } from '../shared/i18n';
import { online } from '../shared/network';
import { getPref, setPref } from '../shared/prefs';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { vaultState } from '../shared/vault';
import { CitizenShell } from './CitizenShell';
import { formatDate } from './result/data';
import { composeText } from './scam/api';

/**
 * The person's in-app messages (GET /v1/notifications: the in-app copy of every message, newest first).
 * Unread means newer than the last time this person opened the inbox; that time is kept per person on the
 * phone (prefs). Fetched when the app comes back into view and at most once a minute while it is visible
 * and online. Citizens only: a helper acting for a family would see the helper's own messages here.
 */
interface Box {
  items: readonly NotificationOut[] | null;
  failure: ApiFailure | null;
}
export const inbox = signal<Box>({ items: null, failure: null });
const seen = signal(0);
let seenFor: string | null = null;
let last = 0;

/** The signed-in citizen whose messages these are, or null. Reads signals, so a component using it follows them. */
function owner(): string | null {
  const now = session.value;
  return now.status === 'signed-in' && now.active.role === 'citizen' && acting.value === null && vaultState.value !== 'locked' ? now.user.id : null;
}

export async function refreshInbox(force = false): Promise<void> {
  const who = owner();
  if (!who || (!force && Date.now() - last < 60_000)) return;
  last = Date.now();
  if (seenFor !== who) {
    seenFor = who;
    const stored = await getPref(`inboxSeen:${who}`);
    seen.value = typeof stored === 'number' ? stored : 0;
  }
  const result = await call(api.GET('/v1/notifications', { params: { query: { limit: 30 } } }));
  if (owner() !== who) return; // signed out or switched meanwhile: never show one person's messages to another
  inbox.value = result.ok ? { items: result.data.items, failure: null } : { items: inbox.peek().items, failure: result.failure };
}

if (typeof document !== 'undefined') {
  const back = (): void => {
    if (document.visibilityState === 'visible') void refreshInbox(Date.now() - last > 10_000);
  };
  window.addEventListener('focus', back);
  document.addEventListener('visibilitychange', back);
  setInterval(() => {
    if (document.visibilityState === 'visible' && online.peek()) void refreshInbox();
  }, 60_000);
}

onSessionEnd(() => {
  inbox.value = { items: null, failure: null };
  seen.value = 0;
  seenFor = null;
  last = 0;
});

/** The bell at the top of a signed-in citizen's screens, with the number of new messages. */
/** `night`: on the night band at the top of home, styled like the back button there. */
export function Bell({ night }: { night: boolean }) {
  const { route } = useLocation();
  const show = owner() !== null;
  useEffect(() => {
    if (show) void refreshInbox();
  }, [show]);
  if (!show) return null;
  const count = (inbox.value.items ?? []).filter((item) => Date.parse(item.created_at) > seen.value).length;
  return (
    <button
      type="button"
      onClick={() => route('/messages')}
      aria-label={`${t('inbox_title')}: ${count}`}
      class={`relative inline-flex min-h-tap min-w-tap items-center justify-center rounded-full border-2 ${night ? 'border-night-line bg-night-2 text-night-ink hover:bg-night-3' : 'border-line-strong bg-paper text-ink hover:bg-surface'}`}
    >
      <Pictogram name="bell" size={30} />
      {count > 0 ? (
        <span aria-hidden="true" class="rh-ltr absolute -end-1 -top-1 grid min-w-6 place-items-center rounded-full bg-danger px-1 text-sm font-bold text-white">
          {count}
        </span>
      ) : null}
    </button>
  );
}

/** "My messages": every message, newest first, in the language it was written in, with its time and check code. */
export function InboxScreen() {
  const { route } = useLocation();
  const box = inbox.value;
  const ui = lang.value;
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  useEffect(() => {
    void refreshInbox(true);
  }, []);
  const newest = box.items?.[0];
  useEffect(() => {
    const who = owner();
    if (!newest || !who) return;
    const at = Date.parse(newest.created_at);
    if (at > seen.peek()) {
      seen.value = at;
      void setPref(`inboxSeen:${who}`, at);
    }
  }, [newest?.id]);

  const check = (body: string): void => {
    composeText.value = body;
    route('/scam');
  };

  return (
    <CitizenShell onBack={() => route('/')} prompt="inbox_prompt">
      <div class="flex items-center gap-4">
        <Pictogram name="bell" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('inbox_title')}
        </h1>
      </div>
      {acting.value !== null ? (
        <ScreenState kind="denied" heading="h2" />
      ) : box.items === null ? (
        box.failure ? (
          <FailureState failure={box.failure} heading="h2" onRetry={() => void refreshInbox(true)} />
        ) : (
          <ScreenState kind="loading" />
        )
      ) : box.items.length === 0 ? (
        <ScreenState kind="empty" heading="h2" />
      ) : (
        <>
          <p class="text-lg text-ink-muted">{t('inbox_prompt')}</p>
          <ul class="flex flex-col gap-3">
            {box.items.map((item) => {
              return (
                <li key={item.id} class="flex flex-col gap-2 rounded-lg border-2 border-line bg-paper p-3">
                  <div class="flex items-center gap-3">
                    <Pictogram name="message" size={36} class="text-primary" />
                    <p class="flex-1 text-base text-ink-muted">{formatDate(item.created_at, ui, true)}</p>
                    <AudioPrompt
                      speech={{ id: `inbox:${item.id}`, items: [{ key: 'inbox.dynamic', text: item.body, lang: item.lang === 'en' ? 'en' : 'ur' }] }}
                    />
                  </div>
                  {/* Server text, shown as text in the language and direction it was written in. */}
                  <p class="text-lg" lang={item.lang === 'ru' ? 'ur-Latn' : item.lang} dir={item.lang === 'ur' ? 'rtl' : 'ltr'}>
                    {item.body}
                  </p>
                  {item.verify_code ? (
                    <div class="flex flex-wrap items-center gap-3">
                      <p class="text-base text-ink-muted">
                        {t('paid_code_label')}: <span class="rh-ltr font-mono font-bold text-ink">{item.verify_code}</span>
                      </p>
                      <Button size="md" variant="secondary" icon="shield" onClick={() => check(item.body)}>
                        {t('scam_check')}
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </CitizenShell>
  );
}
