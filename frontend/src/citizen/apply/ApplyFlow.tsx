import { useEffect, useState } from 'preact/hooks';
import type { ApiFailure } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { t } from '../../shared/i18n';
import { Redirect } from '../../shared/routing';
import { CitizenShell } from '../CitizenShell';
import { CardStep } from './CardStep';
import { ConsentDeclined, ConsentStep } from './ConsentStep';
import { consentNeeded, draft, firstOpenStep, hasApplication, isStep, lastSubmit, startOrResume, stepPath, type StepId } from './flow';
import { HouseholdStep, IncomeStep, NameStep, TRI_STEPS, TriStep } from './QuestionSteps';
import { ReviewStep } from './ReviewStep';

function stepScreen(step: StepId) {
  switch (step) {
    case 'consent':
      return <ConsentStep />;
    case 'card':
      return <CardStep />;
    case 'name':
      return <NameStep />;
    case 'household':
      return <HouseholdStep />;
    case 'income':
      return <IncomeStep />;
    case 'widow':
    case 'disability':
    case 'aid':
      return <TriStep key={step} spec={TRI_STEPS[step]} />;
    case 'review':
      return <ReviewStep />;
  }
}

/**
 * /apply and /apply/{step}. Loads the draft first (resuming an unfinished
 * application from the server), then shows the step in the address, or the
 * first step that still needs an answer.
 */
export function ApplyFlow({ step }: { step: string | undefined }) {
  const d = draft.value;
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Sent from the review screen while waiting in the outbox: show the result, not a new draft.
  const sentFromReview = !d && step === 'review' && lastSubmit.value !== null;

  useEffect(() => {
    if (draft.peek() || sentFromReview) return;
    let live = true;
    setFailure(null);
    void startOrResume().then((result) => {
      if (live && !result.ok) setFailure(result.failure);
    });
    return () => {
      live = false;
    };
  }, [attempt, d === null]);

  if (step === 'declined') return <ConsentDeclined />;
  if (sentFromReview) return <Redirect to="/result" />;

  if (!d) {
    return (
      <CitizenShell prompt={failure ? undefined : 'apply_starting'}>
        {failure ? (
          <FailureState failure={failure} onRetry={() => setAttempt((n) => n + 1)} />
        ) : (
          <ScreenState kind="loading" body={t('apply_starting')} />
        )}
      </CitizenShell>
    );
  }

  // A write was refused for missing consent: ask for it again.
  if (consentNeeded.value && step !== 'consent') return <Redirect to={stepPath('consent')} />;

  if (!isStep(step)) return <Redirect to={stepPath(firstOpenStep(d))} />;

  // Nothing after consent works without an application (on the server, or waiting in the outbox).
  if (step !== 'consent' && !hasApplication(d)) return <Redirect to={stepPath('consent')} />;
  // The name question needs a name read from the card.
  if (step === 'name' && !d.cardName) return <Redirect to={stepPath(firstOpenStep(d))} />;

  return stepScreen(step);
}
