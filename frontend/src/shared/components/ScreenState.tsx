import type { ComponentChildren } from 'preact';
import type { ApiFailure } from '../api/problem';
import { screenKindFor } from '../api/problem';
import { t, type MessageKey } from '../i18n';
import { useFocusOnMount } from '../useFocusOnMount';
import { AudioPrompt } from './AudioPrompt';
import { Button } from './Button';
import { Pictogram, type PictogramName } from './Pictogram';
import { Spinner } from './Spinner';

/**
 * The states every screen must handle (docs/DESIGN.md): loading, empty, error,
 * offline, permission denied, not found. Success is the screen itself.
 */
export type ScreenKind = 'loading' | 'empty' | 'error' | 'offline' | 'denied' | 'not_found';

const DEFAULTS: Record<Exclude<ScreenKind, 'loading'>, { icon: PictogramName; title: MessageKey; body: MessageKey; tone: string }> = {
  empty: { icon: 'document', title: 'state_empty_title', body: 'state_empty_body', tone: 'text-ink-muted' },
  error: { icon: 'warning', title: 'state_error_title', body: 'state_error_body', tone: 'text-danger' },
  offline: { icon: 'offline', title: 'state_offline_title', body: 'state_offline_body', tone: 'text-ink' },
  denied: { icon: 'lock', title: 'state_denied_title', body: 'state_denied_body', tone: 'text-ink' },
  not_found: { icon: 'warning', title: 'state_not_found_title', body: 'state_not_found_body', tone: 'text-ink-muted' },
};

interface ScreenStateProps {
  kind: ScreenKind;
  density?: 'citizen' | 'staff';
  /** Override the default title or body (plain text, never HTML). */
  title?: string;
  body?: string;
  /** Shows a "Try again" button. */
  onRetry?: () => void;
  /** request_id from the problem response, shown so a helper can trace it. */
  requestId?: string | undefined;
  /** h1 when the state is the whole screen (default), h2 inside a larger page. */
  heading?: 'h1' | 'h2';
  /** Extra actions under the message (for example "Go to the start"). */
  children?: ComponentChildren;
}

export function ScreenState({
  kind,
  density = 'citizen',
  title,
  body,
  onRetry,
  requestId,
  heading = 'h1',
  children,
}: ScreenStateProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>(heading === 'h1' && kind !== 'loading');
  const Heading = heading;

  if (kind === 'loading') {
    return density === 'citizen' ? (
      <div role="status" class="flex flex-1 flex-col items-center justify-center gap-4 py-12 text-primary">
        <Spinner size={64} />
        <p class="text-xl text-ink">{body ?? t('state_loading')}</p>
      </div>
    ) : (
      <div role="status" class="flex items-center gap-2 px-1 py-3 text-sm text-ink-muted">
        <Spinner size={16} />
        <span>{body ?? 'Loading…'}</span>
      </div>
    );
  }

  const spec = DEFAULTS[kind];
  const titleText = title ?? t(spec.title);
  const bodyText = body ?? t(spec.body);

  if (density === 'staff') {
    return (
      <div role={kind === 'error' ? 'alert' : 'status'} class="flex items-start gap-3 rounded-sm border border-line bg-sunken p-3 text-sm">
        <Pictogram name={spec.icon} size={20} class={spec.tone} />
        <div class="flex flex-1 flex-col gap-1">
          <Heading ref={headingRef} tabIndex={-1} class="font-semibold text-ink">
            {titleText}
          </Heading>
          <p class="text-ink-muted">{bodyText}</p>
          {requestId ? <p class="font-mono text-xs text-ink-subtle">request_id {requestId}</p> : null}
          {onRetry || children ? (
            <div class="mt-1 flex flex-wrap gap-2">
              {onRetry ? (
                <Button size="sm" variant="neutral" icon="retry" onClick={onRetry}>
                  Retry
                </Button>
              ) : null}
              {children}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div role={kind === 'error' ? 'alert' : 'status'} class="flex flex-1 flex-col items-center gap-5 py-8 text-center">
      <Pictogram name={spec.icon} size={96} class={spec.tone} />
      <Heading ref={headingRef} tabIndex={-1} class="text-2xl font-bold text-ink">
        {titleText}
      </Heading>
      <p class="max-w-prose text-lg text-ink-muted">{bodyText}</p>
      <AudioPrompt prompt={spec.body} autoPlay />
      {onRetry ? (
        <Button size="lg" icon="retry" block onClick={onRetry}>
          {t('retry')}
        </Button>
      ) : null}
      {children}
      {requestId ? (
        <p class="text-sm text-ink-muted">
          {t('state_reference', { id: requestId })}
        </p>
      ) : null}
    </div>
  );
}

/** Convenience: render the right state for an API failure. */
export function FailureState({
  failure,
  density = 'citizen',
  onRetry,
  heading,
  children,
}: {
  failure: ApiFailure;
  density?: 'citizen' | 'staff';
  onRetry?: () => void;
  heading?: 'h1' | 'h2';
  children?: ComponentChildren;
}) {
  const kind = screenKindFor(failure);
  return (
    <ScreenState
      kind={kind}
      density={density}
      onRetry={kind === 'denied' || kind === 'not_found' ? undefined : onRetry}
      requestId={failure.problem?.request_id}
      heading={heading}
    >
      {children}
    </ScreenState>
  );
}
