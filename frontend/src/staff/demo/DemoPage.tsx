import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { homePathFor, login, session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { DemoAccount } from '../../shared/api/types';
import { Button } from '../../shared/components/Button';
import { PrototypeFooter } from '../../shared/components/PrototypeFooter';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useTemporaryLang } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';

type Load =
  | { kind: 'loading' }
  | { kind: 'hidden' }
  | { kind: 'failed'; failure: ApiFailure }
  | { kind: 'ready'; accounts: DemoAccount[] };

const rowKey = (a: DemoAccount): string => `${a.tenant_slug}|${a.identifier}|${a.role}`;

/**
 * /demo: mock demo accounts with one-click sign-in, for judges and testing.
 * Lazy chunk. Looks like any unknown page when the API answers 404 (outside
 * demo and dev).
 */
export default function DemoPage() {
  useTemporaryLang('en');
  const { route } = useLocation();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [pending, setPending] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ key: string; message: string } | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(load.kind === 'ready');

  const fetchAccounts = async (): Promise<void> => {
    setLoad({ kind: 'loading' });
    const result = await call(api.GET('/v1/demo/accounts'));
    if (result.ok) setLoad({ kind: 'ready', accounts: result.data.accounts });
    else if (result.failure.kind === 'not_found') setLoad({ kind: 'hidden' });
    else setLoad({ kind: 'failed', failure: result.failure });
  };

  useEffect(() => {
    void fetchAccounts();
  }, []);

  const use = async (account: DemoAccount): Promise<void> => {
    const key = rowKey(account);
    setPending(key);
    setRowError(null);
    const result = await login({
      identifier: account.identifier,
      secret: account.secret,
      tenant_slug: account.tenant_slug,
    });
    setPending(null);
    if (result.ok) {
      route(homePathFor(result.role));
      return;
    }
    const f = result.failure;
    setRowError({
      key,
      message:
        f.kind === 'offline'
          ? 'No network.'
          : `Sign-in failed${f.status ? ` (${f.status})` : ''}${f.problem ? `: ${f.problem.title}` : ''}.`,
    });
  };

  const current = session.value;

  let body;
  if (load.kind === 'loading') body = <ScreenState kind="loading" density="staff" />;
  else if (load.kind === 'hidden')
    body = <ScreenState kind="not_found" density="staff" title="Page not found" body="This page does not exist." />;
  else if (load.kind === 'failed')
    body = <FailureState failure={load.failure} density="staff" onRetry={() => void fetchAccounts()} />;
  else if (load.accounts.length === 0)
    body = <ScreenState kind="empty" density="staff" title="No demo accounts" body="Run the seed (npm run seed) to create them." />;
  else
    body = (
      <>
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h1 ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
            Demo accounts
          </h1>
          <p class="text-ink-muted">
            {current.status === 'signed-in'
              ? `Signed in as ${current.user.display_name} (${current.active.role}, ${current.active.tenant_name}).`
              : 'Not signed in.'}
          </p>
        </div>
        <p class="rounded-sm border border-warning-ink bg-warning-soft px-2 py-1.5 text-warning-ink">
          Mock accounts for judges and testing. Every account, number and record here is simulated.
        </p>
        <div class="overflow-x-auto rounded-sm border border-line">
          <table class="w-full border-collapse text-start">
            <thead class="bg-sunken text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th scope="col" class="px-2 py-1.5 text-start">Account</th>
                <th scope="col" class="px-2 py-1.5 text-start">Role</th>
                <th scope="col" class="px-2 py-1.5 text-start">Tenant</th>
                <th scope="col" class="px-2 py-1.5 text-start">Identifier</th>
                <th scope="col" class="px-2 py-1.5 text-start">Secret</th>
                <th scope="col" class="px-2 py-1.5 text-start">
                  <span class="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {load.accounts.map((account) => {
                const key = rowKey(account);
                return (
                  <tr key={key} class="border-t border-line align-top">
                    <td class="px-2 py-1.5">
                      <span class="font-semibold">{account.label}</span>
                      <span class="ms-2 font-mono text-xs text-ink-subtle">{account.kind}</span>
                      {rowError?.key === key ? (
                        <p role="alert" class="text-danger">
                          {rowError.message}
                        </p>
                      ) : null}
                    </td>
                    <td class="px-2 py-1.5 font-mono">{account.role}</td>
                    <td class="px-2 py-1.5">{account.tenant_name}</td>
                    <td class="rh-ltr px-2 py-1.5 font-mono">{account.identifier}</td>
                    <td class="rh-ltr px-2 py-1.5 font-mono">{account.secret}</td>
                    <td class="px-2 py-1.5 text-end">
                      <Button
                        size="sm"
                        variant="primary"
                        busy={pending === key}
                        disabled={pending !== null}
                        onClick={() => void use(account)}
                      >
                        Use this account
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p class="text-xs text-ink-muted">
          Citizen and helper accounts open the citizen app at /. Staff accounts open the console at /staff.
        </p>
      </>
    );

  return (
    <div class="flex min-h-dvh flex-col bg-paper text-sm text-ink">
      <main class="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-3 p-4">{body}</main>
      <PrototypeFooter density="staff" />
    </div>
  );
}
