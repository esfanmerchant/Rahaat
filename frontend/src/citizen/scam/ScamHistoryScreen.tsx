import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import type { ApiFailure } from '../../shared/api/problem';
import type { MyScamReport } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { Pictogram } from '../../shared/components/Pictogram';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { isMessageKey, lang, t, type Lang } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { InlineFailure } from '../apply/parts';
import { CitizenShell } from '../CitizenShell';
import { myChecks } from './api';
import { certaintyOf, reviewKey, TONE_BOX } from './parts';

/** Day and time in the person's language, with 0-9 digits. */
function formatWhen(iso: string, code: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(code === 'ur' ? 'ur-PK-u-nu-latn' : 'en-GB', {
    day: 'numeric',
    month: 'long',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

type Loaded =
  | { state: 'loading' }
  | { state: 'failed'; failure: ApiFailure }
  | { state: 'ready'; items: MyScamReport[]; next: string | null };

/** My checks, newest first: a picture and colour per answer, the date, and whether a person is checking. */
export function ScamHistoryScreen() {
  const { route } = useLocation();
  const [loaded, setLoaded] = useState<Loaded>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [more, setMore] = useState<{ busy: boolean; failure: ApiFailure | null }>({ busy: false, failure: null });
  const headingRef = useFocusOnMount<HTMLHeadingElement>(loaded.state === 'ready');
  const code = lang.value;

  useEffect(() => {
    let live = true;
    setLoaded({ state: 'loading' });
    void myChecks().then((result) => {
      if (!live) return;
      setLoaded(
        result.ok
          ? { state: 'ready', items: result.data.items, next: result.data.next_cursor ?? null }
          : { state: 'failed', failure: result.failure },
      );
    });
    return () => {
      live = false;
    };
  }, [attempt]);

  const loadMore = async (): Promise<void> => {
    if (loaded.state !== 'ready' || !loaded.next) return;
    setMore({ busy: true, failure: null });
    const result = await myChecks(loaded.next);
    if (result.ok) {
      setLoaded({ state: 'ready', items: [...loaded.items, ...result.data.items], next: result.data.next_cursor ?? null });
      setMore({ busy: false, failure: null });
    } else {
      setMore({ busy: false, failure: result.failure });
    }
  };

  const back = (): void => route('/scam');
  if (loaded.state !== 'ready') {
    return (
      <CitizenShell onBack={back}>
        {loaded.state === 'failed' ? (
          <FailureState failure={loaded.failure} onRetry={() => setAttempt((n) => n + 1)} />
        ) : (
          <ScreenState kind="loading" />
        )}
      </CitizenShell>
    );
  }
  if (loaded.items.length === 0) {
    return (
      <CitizenShell onBack={back}>
        <ScreenState kind="empty" title={t('scam_history_empty_title')} body={t('scam_history_empty_body')}>
          <Button size="lg" icon="shield" block onClick={() => route('/scam')}>
            {t('home_scam')}
          </Button>
        </ScreenState>
      </CitizenShell>
    );
  }
  return (
    <CitizenShell onBack={back} prompt="scam_history_prompt">
      <div class="flex items-center gap-4">
        <Pictogram name="clock" size={56} class="text-primary" />
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('scam_history')}
        </h1>
      </div>
      <ul class="flex flex-col gap-3">
        {loaded.items.map((item) => {
          const spec = certaintyOf(item.certainty);
          const review = reviewKey(item.review);
          return (
            <li key={item.id}>
              <a
                href={`/scam/answer/${item.id}`}
                class="flex min-h-tap-lg items-center gap-3 rounded-lg border-2 border-line-strong bg-paper p-2 text-ink no-underline hover:bg-surface"
              >
                <span class={`flex size-14 shrink-0 items-center justify-center rounded-full border-2 ${TONE_BOX[spec.tone]}`}>
                  <Pictogram name={spec.icon} size={36} />
                </span>
                <span class="flex min-w-0 flex-1 flex-col">
                  <span class="text-lg font-semibold">{t(spec.key)}</span>
                  {item.label && isMessageKey(`scam_label_${item.label}`) ? (
                    <span class="text-base text-ink">{t(`scam_label_${item.label}` as Parameters<typeof t>[0])}</span>
                  ) : null}
                  <span class="text-sm text-ink-muted">{formatWhen(item.checked_at, code)}</span>
                  {review ? (
                    <span class="flex items-center gap-1 text-sm font-semibold text-info-strong">
                      <Pictogram name={item.review.status === 'waiting' ? 'clock' : 'person-help'} size={20} />
                      {t(review)}
                    </span>
                  ) : null}
                </span>
                <Pictogram name="forward" size={28} class="text-ink-muted" />
              </a>
            </li>
          );
        })}
      </ul>
      {more.failure ? <InlineFailure failure={more.failure} /> : null}
      {loaded.next ? (
        <Button size="md" variant="secondary" icon="plus" block busy={more.busy} onClick={() => void loadMore()}>
          {t('scam_history_more')}
        </Button>
      ) : null}
      <Button size="lg" icon="shield" block onClick={() => route('/scam')} class="mt-auto">
        {t('home_scam')}
      </Button>
    </CitizenShell>
  );
}
