import { useState } from 'preact/hooks';
import { login } from '../shared/api/auth';
import type { ApiFailure } from '../shared/api/problem';
import { demoMode } from '../shared/api/system';
import { Button } from '../shared/components/Button';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { online } from '../shared/network';
import { useFocusOnMount } from '../shared/useFocusOnMount';

function messageFor(failure: ApiFailure): string {
  switch (failure.kind) {
    case 'unauthenticated':
      return 'Email or password is incorrect.';
    case 'locked':
    case 'rate_limited':
      return failure.problem?.detail ?? 'Too many attempts. Wait a few minutes and try again.';
    case 'validation':
      return failure.problem?.errors?.map((e) => `${e.field}: ${e.message}`).join(' ') ?? 'Check the email and password.';
    case 'offline':
      return 'No network connection. Connect and try again.';
    case 'network':
      return 'The server did not answer. Try again.';
    default:
      return `Sign-in failed${failure.status ? ` (${failure.status})` : ''}. Try again.`;
  }
}

/** Staff sign-in: email and password. On success the /staff/login guard routes by role. */
export function StaffLogin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();

  const onSubmit = async (event: Event): Promise<void> => {
    event.preventDefault();
    if (!online.peek()) {
      setFailure({ kind: 'offline' });
      return;
    }
    setBusy(true);
    setFailure(null);
    const result = await login({ identifier: email.trim(), secret: password });
    setBusy(false);
    if (!result.ok) {
      setFailure(result.failure);
      setPassword('');
    }
  };

  const input =
    'h-9 w-full rounded-sm border border-line-strong bg-paper px-2 text-sm text-ink disabled:bg-sunken';

  return (
    <div class="flex min-h-dvh flex-col bg-sunken text-sm text-ink">
      <main class="flex flex-1 items-start justify-center p-4 pt-16">
        <form
          onSubmit={(event) => void onSubmit(event)}
          noValidate
          class="flex w-full max-w-sm flex-col gap-3 rounded-sm border border-line bg-paper p-5"
          aria-labelledby="staff-login-title"
        >
          <div class="flex items-center justify-between gap-2">
            <h1 id="staff-login-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
              Rahat staff console
            </h1>
            <span class="rounded-sm border border-line-strong px-1.5 font-mono text-xs uppercase tracking-wide text-ink-muted">
              Prototype
            </span>
          </div>
          <p class="text-ink-muted">Officers, admins and auditors sign in here.</p>

          <label class="flex flex-col gap-1">
            <span class="font-semibold">Email</span>
            <input
              class={input}
              type="email"
              name="email"
              autoComplete="username"
              required
              disabled={busy}
              value={email}
              onInput={(event) => setEmail(event.currentTarget.value)}
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="font-semibold">Password</span>
            <input
              class={input}
              type="password"
              name="password"
              autoComplete="current-password"
              required
              disabled={busy}
              value={password}
              onInput={(event) => setPassword(event.currentTarget.value)}
            />
          </label>

          {failure ? (
            <p role="alert" class="rounded-sm border border-danger bg-danger-soft px-2 py-1.5 text-danger">
              {messageFor(failure)}
              {failure.problem?.request_id ? (
                <span class="block font-mono text-xs">request_id {failure.problem.request_id}</span>
              ) : null}
            </p>
          ) : null}

          <Button type="submit" size="sm" busy={busy} disabled={email.trim() === '' || password === ''} class="h-9">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>

          <div class="flex justify-between gap-2 text-xs">
            <a href="/" class="text-info-strong underline">
              Citizen app
            </a>
            {demoMode.value ? (
              <a href="/demo" class="text-info-strong underline">
                Demo accounts
              </a>
            ) : null}
          </div>
        </form>
      </main>
      <PrototypeFooter density="staff" />
    </div>
  );
}
