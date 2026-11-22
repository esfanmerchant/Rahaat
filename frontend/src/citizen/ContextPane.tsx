import { useEffect, useState } from 'preact/hooks';
import { acting } from '../shared/acting';
import { session } from '../shared/api/auth';
import { Emblem } from '../shared/components/Emblem';
import { Monogram } from '../shared/components/Monogram';
import { Pictogram, type PictogramName } from '../shared/components/Pictogram';
import { PROTOTYPE_LABEL_EN, PROTOTYPE_LABEL_UR } from '../shared/components/PrototypeFooter';
import { lang, t, type MessageKey } from '../shared/i18n';
import { online } from '../shared/network';
import { draft, STEPS, type StepId } from './apply/flow';
import { JOURNEY_STEPS, stepsDone } from './Journey';
import { StarBullet, StarPath, type PathItem } from './JourneyPath';
import { ensureJourney, journeyStatus } from './journeyStore';

/** What the left pane shows beside the right pane's content. */
export type PaneSpec =
  /** `reveal`: light the "decided" star late, in step with the verdict reveal. */
  | { kind: 'journey'; reveal?: boolean }
  | { kind: 'apply'; step: StepId };

const STEP_LABEL: Record<StepId, MessageKey> = {
  consent: 'step_consent',
  card: 'step_card',
  name: 'step_name',
  household: 'step_household',
  income: 'step_income',
  widow: 'step_widow',
  disability: 'step_disability',
  aid: 'step_aid',
  review: 'step_review',
};

const STEP_ICON: Record<StepId, PictogramName> = {
  consent: 'lock',
  card: 'camera',
  name: 'person',
  household: 'family',
  income: 'payment',
  widow: 'widow',
  disability: 'disability',
  aid: 'payment',
  review: 'document',
};

/** A value that follows `target` after a delay, so a star can light a moment after the reveal begins. */
function useLate(target: number, from: number, ms: number, on: boolean): number {
  const [value, setValue] = useState(on ? from : target);
  useEffect(() => {
    if (!on) {
      setValue(target);
      return undefined;
    }
    const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const id = window.setTimeout(() => setValue(target), reduced ? 0 : ms);
    return () => window.clearTimeout(id);
  }, [target, on, ms]);
  return value;
}

function Brand({ size }: { size: number }) {
  return (
    <div class="flex items-center gap-4">
      <Emblem size={size} tone="night" class="drop-shadow-glow" />
      <p class="flex flex-col leading-none" aria-label={t('app_name')}>
        <span lang="ur" dir="rtl" class="text-4xl font-black text-noor">
          راحت
        </span>
        <span lang="en" dir="ltr" class="text-2xl font-black tracking-tight text-night-ink">
          Rahat
        </span>
      </p>
    </div>
  );
}

/**
 * The person's context, at 1024 px and wider: the program's lamp and name, who is signed in, where the
 * application is (or the questions, while applying), a short warning and the prototype label. It sits on the
 * night sky, stays in place while the right pane changes, and has its own view-transition name so a route
 * change does not slide it.
 */
export function ContextPane({ spec }: { spec: PaneSpec }) {
  const now = session.value;
  const signedIn = now.status === 'signed-in';
  const family = acting.value;
  const name = now.status !== 'signed-in' ? '' : family ? (lang.value === 'ur' && family.nameUr ? family.nameUr : family.name) : now.user.display_name;
  // A helper has no application of their own: the journey and the questions belong to the family they act for.
  const ownJourney = now.status === 'signed-in' && (now.active.role !== 'helper' || family !== null);
  const status = journeyStatus.value;
  const offline = !online.value;

  useEffect(() => {
    if (ownJourney) void ensureJourney();
  }, [ownJourney, family?.personId]);

  const hour = new Date().getHours();
  const greeting: MessageKey = hour < 12 ? 'greeting_morning' : hour < 17 ? 'greeting_afternoon' : 'greeting_evening';
  const done = stepsDone(status ?? null);
  const reveal = spec.kind === 'journey' && spec.reveal === true;
  // After a decision the "decided" star lights a moment later, with the verdict.
  const shownDone = useLate(done, Math.min(done, 1), 1900, reveal && done >= 3);
  const stopped = status === 'rejected' || status === 'withdrawn';

  const applySteps: PathItem[] = STEPS.filter((id) => id !== 'name' || draft.value?.cardName).map((id) => ({ key: id, label: STEP_LABEL[id] }));
  const applyIndex = spec.kind === 'apply' ? Math.max(0, applySteps.findIndex((item) => item.key === spec.step)) : 0;

  return (
    <aside
      aria-label={t('app_name')}
      class="rh-pane rh-night-sky relative flex flex-col overflow-hidden"
      style={{ position: 'sticky', top: offline ? '44px' : '0px', height: offline ? 'calc(100dvh - 44px)' : '100dvh' }}
    >
      <div aria-hidden="true" class="rh-lattice-night absolute inset-0" />
      {/* A large, faint emblem turning slowly in the corner: the lamp the whole product is about. */}
      <Emblem size={520} tone="night" class="pointer-events-none absolute -bottom-40 -end-40 opacity-[0.07] motion-safe:animate-spin-slow" />
      <div class="relative flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-10 py-8 xl:px-14">
        <Brand size={spec.kind === 'apply' ? 64 : signedIn ? 88 : 140} />

        {signedIn ? (
          <div class="flex items-center gap-4">
            <Monogram name={name} size={56} />
            <p class="text-2xl font-extrabold text-night-ink" dir="auto">
              {t(greeting, { name })}
            </p>
          </div>
        ) : (
          <p class="max-w-sm text-xl text-night-muted">{t('program_tagline')}</p>
        )}

        {signedIn && !ownJourney ? <p class="max-w-sm text-xl text-night-muted">{t('program_tagline')}</p> : null}

        {ownJourney && spec.kind === 'journey' ? (
          <StarPath items={JOURNEY_STEPS.map((s) => ({ key: s.key, label: s.key }))} done={shownDone} stopped={stopped} title="journey_title" />
        ) : null}

        {ownJourney && spec.kind === 'apply' ? (
          <>
            <div class="flex items-center gap-5">
              <span class="grid size-36 shrink-0 place-items-center rounded-full border-2 border-noor/60 bg-night-2 text-noor shadow-glow">
                <Pictogram name={STEP_ICON[spec.step]} size={80} />
              </span>
              <p class="text-lg text-night-muted">{t('pane_listen_hint')}</p>
            </div>
            <StarPath items={applySteps} done={applyIndex} title="pane_steps_title" compact />
          </>
        ) : null}

        <div class="mt-auto flex flex-col gap-4">
          {spec.kind === 'journey' ? (
            <div class="flex items-start gap-3 rounded-xl border border-night-line bg-night-2/70 p-4">
              <Pictogram name="shield" size={36} class="shrink-0 text-madder-glow" />
              <div class="flex flex-col gap-1">
                <p class="flex items-center gap-2 text-base font-bold text-night-ink">
                  <StarBullet class="text-noor" />
                  {t('warn_title')}
                </p>
                <p class="text-base text-night-muted">{t('scam_never_pay')}</p>
              </div>
            </div>
          ) : null}
          <div class="flex flex-col gap-1 border-t border-night-line pt-3 text-sm text-night-muted">
            <p lang="en" dir="ltr">
              {PROTOTYPE_LABEL_EN}
            </p>
            <p lang="ur" dir="rtl">
              {PROTOTYPE_LABEL_UR}
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}
